#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# GIMP 3 Plugin: AI Remove Background
#
# Base structure & rembg integration: ismdevteam (https://github.com/ismdevteam/gimp3-rembg-plugin)
# Extra options (Mask/Alpha/Square): Tech Archive / Guy Vardi (https://github.com/Tech-Archive/gimp-rembg-plugin)
# Withoutbg: https://github.com/withoutbg/withoutbg-python
# withoutbg integration & refinements: Chester
#
# License: Apache 2.0

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('GimpUi', '3.0')
from gi.repository import GimpUi
from gi.repository import GLib
from gi.repository import Gio
from rembg import new_session, remove
import os
import sys
import tempfile
import threading
import importlib.util

def _(message): return GLib.dgettext(None, message)

# Check for withoutbg availability without importing heavy dependencies at startup
HAS_WITHOUTBG = importlib.util.find_spec('withoutbg') is not None

modelList = (
    "u2net",
    "u2net_human_seg",
    "u2net_cloth_seg",
    "u2netp",
    "silueta",
    "isnet-general-use",
    "isnet-anime",
    "sam"
)
if HAS_WITHOUTBG:
    modelList = modelList + ("withoutbg",)


class Goat(Gimp.PlugIn):
    """Main plugin class for AI Background Removal."""

    def do_query_procedures(self):
        return ["plug-in-ai-remove-background"]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name,
                                            Gimp.PDBProcType.PLUGIN,
                                            self.run, None)
        procedure.set_image_types("*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_menu_label(_("AI Remove Background"))
        procedure.set_icon_name(GimpUi.ICON_GEGL)
        procedure.add_menu_path('<Image>/Filters/')
        procedure.set_documentation(
            _("Removes the background using AI models (rembg/withoutbg)."),
            _("Supports alpha matting, mask generation, and square cropping."),
            name)
        procedure.set_attribution("ismdevteam / Chester", "GPLv3", "2024-2026")
        return procedure

    def store_layer(self, image, drawable, tmp):
        """Exports the given drawable to a temporary PNG file preserving transparency."""
        interlace, compression = 0, 2
        width, height = drawable.get_width(), drawable.get_height()
        tmp_img = Gimp.Image.new(width, height, image.get_base_type())
        tmp_layer = Gimp.Layer.new_from_drawable(drawable, tmp_img)
        tmp_img.insert_layer(tmp_layer, None, 0)

        pdb_proc = Gimp.get_pdb().lookup_procedure('file-png-export')
        pdb_config = pdb_proc.create_config()
        pdb_config.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
        pdb_config.set_property('image', tmp_img)
        pdb_config.set_property('file', Gio.File.new_for_path(tmp))
        pdb_config.set_property('options', None)
        pdb_config.set_property('interlaced', interlace)
        pdb_config.set_property('compression', compression)
        pdb_config.set_property('bkgd', True)
        pdb_config.set_property('offs', False)
        pdb_config.set_property('phys', True)
        pdb_config.set_property('time', True)
        pdb_config.set_property('save-transparent', True)
        pdb_proc.run(pdb_config)
        tmp_img.delete()

    def progress_init(self, msg):
        """Initializes the GIMP progress bar with compatibility fallback."""
        try:
            Gimp.progress_init(msg, None)
        except TypeError:
            Gimp.progress_init(msg)

    def pdb_run(self, name, **props):
        """
        Executes a PDB procedure by name with given properties.
        Handles missing 'run-mode' property in some GIMP 3 procedures.
        Raises RuntimeError if the procedure fails or is not found.
        """
        proc = Gimp.get_pdb().lookup_procedure(name)
        if proc is None:
            raise RuntimeError("Procedure not found: " + name)

        cfg = proc.create_config()
        try:
            cfg.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
        except TypeError:
            pass

        for k, v in props.items():
            cfg.set_property(k, v)

        result = proc.run(cfg)
        if result.index(0) != Gimp.PDBStatusType.SUCCESS:
            raise RuntimeError("Procedure failed: " + name)
        return result

    def replace_op(self):
        """Returns the correct ChannelOp enum for REPLACE across different GIMP versions."""
        for enum_name in ('ChannelOperation', 'ChannelOps', 'ChannelOp'):
            e = getattr(Gimp, enum_name, None)
            if e is not None:
                try:
                    return e.REPLACE
                except AttributeError:
                    pass
        return 0

    def alpha_matting_refine(self, input_path, rgba, erode_size, fg_thr=240, bg_thr=10):
        """
        Refines the alpha channel using closed-form matting (pymatting).
        Uses the initial AI alpha as a trimap to recover fine details (hair/fur).
        """
        import numpy as np
        from PIL import Image
        from scipy.ndimage import binary_erosion, binary_dilation
        from pymatting import estimate_alpha_cf

        img = Image.open(input_path).convert('RGB')
        img_np = np.asarray(img, dtype=np.float64) / 255.0
        mask = np.asarray(rgba.getchannel('A'), dtype=np.float64) / 255.0

        is_fg = mask > fg_thr / 255.0
        is_bg = mask < bg_thr / 255.0

        if erode_size and erode_size > 0:
            se = np.ones((erode_size, erode_size), dtype=bool)
            is_fg = binary_erosion(is_fg, structure=se)
            is_bg = binary_dilation(is_bg, structure=se)

        trimap = np.full(mask.shape, 0.5)
        trimap[is_fg] = 1.0
        trimap[is_bg] = 0.0

        alpha = estimate_alpha_cf(img_np, trimap)
        out = np.dstack([img_np, alpha])
        out = (np.clip(out, 0.0, 1.0) * 255.0).astype(np.uint8)
        return Image.fromarray(out, 'RGBA')

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        """Main execution entry point for the plugin."""
        if len(drawables) != 1:
            msg = _("Procedure '{}' only works with one drawable.").format(procedure.get_name())
            error = GLib.Error.new_literal(Gimp.PlugIn.error_quark(), msg, 0)
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, error)

        drawable = drawables[0]

        # Defaults
        model_name = "withoutbg" if HAS_WITHOUTBG else modelList[0]
        as_mask = True
        alpha_matting = False
        ae_value = 15
        make_square = False

        if run_mode == Gimp.RunMode.INTERACTIVE:
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk
            GimpUi.init("gimp3-rembg-plugin")

            dialog = GimpUi.Dialog(use_header_bar=True,
                                   title=_("AI Remove Background"),
                                   role="plugin-Python3")
            dialog.add_button(_("_Cancel"), Gtk.ResponseType.CANCEL)
            dialog.add_button(_("_OK"), Gtk.ResponseType.OK)

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            box.set_border_width(12)
            dialog.get_content_area().add(box)

            # Model Selector
            model_label = Gtk.Label(label=_("Model:"))
            model_label.set_halign(Gtk.Align.START)
            box.pack_start(model_label, False, False, 0)

            model_selector = Gtk.ComboBoxText()
            for m in modelList:
                model_selector.append_text(m)

            # Set active based on default model name
            try:
                idx = list(modelList).index(model_name)
                model_selector.set_active(idx)
            except ValueError:
                model_selector.set_active(0)

            box.pack_start(model_selector, False, False, 0)

            # Options
            mask_check = Gtk.CheckButton(label=_("Use as Mask"))
            mask_check.set_active(as_mask)
            box.pack_start(mask_check, False, False, 0)

            alpha_check = Gtk.CheckButton(label=_("Alpha Matting"))
            box.pack_start(alpha_check, False, False, 0)

            ae_label = Gtk.Label(label=_("Alpha Matting Erode Size (1-100):"))
            ae_label.set_halign(Gtk.Align.START)
            box.pack_start(ae_label, False, False, 0)

            ae_adj = Gtk.Adjustment(15, 1, 100, 1, 10, 0)
            ae_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=ae_adj)
            ae_scale.set_digits(0)
            ae_scale.set_value_pos(Gtk.PositionType.RIGHT)
            box.pack_start(ae_scale, True, True, 0)

            square_check = Gtk.CheckButton(label=_("Make Square"))
            box.pack_start(square_check, False, False, 0)

            box.show_all()
            response = dialog.run()

            if response == Gtk.ResponseType.OK:
                model_name = model_selector.get_active_text()
                as_mask = mask_check.get_active()
                alpha_matting = alpha_check.get_active()
                ae_value = int(ae_scale.get_value())
                make_square = square_check.get_active()

            dialog.destroy()
            if response != Gtk.ResponseType.OK:
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        tempdir = tempfile.mkdtemp('gimp3-rembg-plugin')
        input_path = os.path.join(tempdir, 'input.png')
        output_path = os.path.join(tempdir, 'output.png')
        undo_started = False
        status = Gimp.PDBStatusType.SUCCESS
        error = None

        try:
            self.progress_init(_("Removing background..."))
            Gimp.progress_update(0.05)

            # Export merged visible layers to temp PNG
            thumb = image.duplicate()
            thumb_layer = thumb.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
            self.store_layer(thumb, thumb_layer, input_path)
            thumb.delete()
            Gimp.progress_update(0.15)

            with open(input_path, 'rb') as i:
                input_data = i.read()

            # Worker thread for AI processing to keep UI responsive
            worker_result = {}
            def worker():
                try:
                    if model_name == 'withoutbg':
                        from withoutbg import WithoutBG
                        wb = WithoutBG.open_weights()
                        res = wb.remove_background(input_path)
                        if alpha_matting:
                            try:
                                res = self.alpha_matting_refine(input_path, res, ae_value)
                            except Exception:
                                pass
                        res.save(output_path)
                        worker_result['saved'] = True
                    else:
                        session = new_session(model_name)
                        if alpha_matting:
                            worker_result['output'] = remove(
                                input_data, session=session,
                                alpha_matting=True,
                                alpha_matting_erode_size=ae_value)
                        else:
                            worker_result['output'] = remove(input_data, session=session)
                except Exception as e:
                    worker_result['error'] = e

            t = threading.Thread(target=worker)
            t.start()
            while t.is_alive():
                Gimp.progress_pulse()
                t.join(0.25)

            if 'error' in worker_result:
                raise worker_result['error']

            if not worker_result.get('saved'):
                with open(output_path, 'wb') as o:
                    o.write(worker_result['output'])

            Gimp.progress_update(0.85)

            # Load result back into GIMP
            result_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE,
                                          Gio.File.new_for_path(output_path))
            if result_image is None:
                raise RuntimeError("Failed to load processed image")

            image.undo_group_start()
            undo_started = True
            result_layer = result_image.get_layers()[0]

            if as_mask:
                # Non-destructive: Apply alpha as a layer mask to the active drawable
                temp_layer = Gimp.Layer.new_from_drawable(result_layer, image)
                image.insert_layer(temp_layer, None, 0)
                try:
                    self.pdb_run('gimp-image-select-item', image=image,
                                 operation=self.replace_op(), item=temp_layer)
                finally:
                    image.remove_layer(temp_layer)

                if drawable.get_mask():
                    try:
                        drawable.remove_mask(Gimp.MaskApplyMode.DISCARD)
                    except Exception:
                        try:
                            drawable.remove_mask(1)
                        except Exception:
                            pass

                mask = drawable.create_mask(Gimp.AddMaskType.SELECTION)
                drawable.add_mask(mask)

                for n in ('gimp-selection-none', 'gimp-image-select-none'):
                    try:
                        self.pdb_run(n, image=image)
                        break
                    except Exception:
                        continue
            else:
                # Destructive-ish: Add cutout as a new top layer
                new_layer = Gimp.Layer.new_from_drawable(result_layer, image)
                image.insert_layer(new_layer, None, 0)
                try:
                    image.set_selected_layer(new_layer)
                except Exception:
                    pass

            if make_square:
                w = image.get_width()
                h = image.get_height()
                max_side = max(w, h)
                image.resize(max_side, max_side,
                             (max_side - w) // 2, (max_side - h) // 2)

            result_image.delete()
            Gimp.progress_update(1.0)

        except Exception as e:
            status = Gimp.PDBStatusType.EXECUTION_ERROR
            error = GLib.Error.new_literal(Gimp.PlugIn.error_quark(), str(e), 0)
        finally:
            if undo_started:
                image.undo_group_end()
            for p in (input_path, output_path):
                try: os.remove(p)
                except Exception: pass
            try: os.rmdir(tempdir)
            except Exception: pass

        Gimp.displays_flush()
        return procedure.new_return_values(status, error)

Gimp.main(Goat.__gtype__, sys.argv)
