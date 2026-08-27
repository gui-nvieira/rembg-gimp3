# GIMP 3 AI Background Remover

A powerful, non-destructive background removal plugin for GIMP 3.x. It integrates state-of-the-art AI models directly into your image editing workflow, supporting both `rembg` and `withoutbg` libraries.

## Features

*   **Dual Engine Support**: Seamlessly switch between `rembg` (U2Net, ISNet, etc.) and `withoutbg`.
*   **Non-Destructive Workflow**: The "Use as Mask" option (enabled by default) applies the AI result as a layer mask to your active layer, preserving original pixels.
*   **Advanced Alpha Matting**: Refine edges (hair, fur) using closed-form matting. Works natively with `rembg` and via a custom `pymatting` implementation for `withoutbg`.
*   **Local Processing**: All inference happens on your machine. No data is sent to external servers.
*   **Responsive UI**: Runs AI processing in a background thread with a progress bar, keeping GIMP responsive during heavy tasks.

## Credits

This plugin is a fusion of existing open-source efforts and new developments:

*   **Base Structure & rembg Integration**: ismdevteam [gimp3-rembg-plugin](https://github.com/ismdevteam/gimp3-rembg-plugin)
*   **Original Concept & Extra Options**: Tech Archive / Guy Vardi [gimp-rembg-plugin](https://github.com/Tech-Archive/gimp-rembg-plugin)
*   **[withoutbg](https://github.com/withoutbg/withoutbg-python) Integration, Alpha Refinement & GIMP 3.2 Porting**: Me

## Installation

### 1. Plugin Installation

1.  Locate your GIMP 3 plug-ins folder. On Linux, it is typically:
    `~/.config/GIMP/3.0/plug-ins/` (or `3.1`,`3.2`, depending on your version).
2.  Clone this repository inside plug-ins folder: `git clone https://github.com/gui-nvieira/rembg-gimp3.git`
3.  Restart GIMP.

### 2. Installing AI Dependencies

Since GIMP runs in its own environment (especially if using Flatpak), you must install the Python libraries into GIMP's internal Python interpreter.

**Find GIMP's Python:**
Open GIMP, go to `Filters` > `Development` > `Python-Fu` > `Console`, and run:
```python
import sys
print(sys.executable)
```
*Note the path printed (e.g., `/usr/bin/python3` for Flatpak).*

**Install `rembg` and `withoutbg`:**
Open your terminal and run (replace `/path/to/gimp/python` with the path found above):


### **CPU only:** 

Native GIMP instalation:
```bash
/path/to/gimp/python -m pip install rembg[cli] withoutbg
```
If using Flatpak:
```bash
flatpak run --share=network --command=bash org.gimp.GIMP
python3 -m pip install rembg[cli] withoutbg
```

### **If you have a Nvidia gpu:**

Native GIMP instalation:
```bash
/path/to/gimp/python -m pip install rembg[cli,gpu] withoutbg
```
If using Flatpak:
```bash
flatpak run --share=network --command=bash org.gimp.GIMP
python3 -m pip install rembg[cli,gpu] withoutbg
```

### **If you have a AMD gpu:**

Native GIMP instalation:
```bash
/path/to/gimp/python -m pip install rembg[rocm,cli] withoutbg
```
If using Flatpak:
```bash
flatpak run --share=network --command=bash org.gimp.GIMP
python3 -m pip install rembg[rocm,cli] withoutbg
```
*Note: The first time you run a model, it will download the weights (~170MB for rembg, ~455MB for withoutbg) from Hugging Face. This happens only once.*

## Usage

Once installed, the plugin is available in the image menu.

**Access:**
Right-click on the canvas (or use the top menu) and navigate to:
`Filters` > `AI Remove Background`

**Options:**

*   **Model**: Select the AI model. `withoutbg` is selected by default if installed. `rembg` models (u2net, isnet, etc.) are also available.
*   **Use as Mask** (Default: ON): Applies the result as a layer mask to the currently active layer. This is non-destructive; your original pixels remain untouched under the mask.
*   **Alpha Matting**: Enables edge refinement.
    *   *Erode Size*: Controls the width of the transition zone for matting. Higher values include more surrounding pixels in the calculation.
*   **Make Square**: Resizes the canvas to a square aspect ratio, centering the content.

**Workflow Tip:**
For the best results with complex subjects (like hair), select `withoutbg` or `u2net`, set `Alpha Matting = 50`, and keep `Use as Mask` checked. You can then manually paint on the generated layer mask to fine-tune the result.

## License
Apache 2.0
