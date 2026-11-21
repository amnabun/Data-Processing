# Chess Data Analytics

Import Lichess games, plot opening popularity, and compare players by rating improvement or playing preferences.

## Build the Windows executable

You need Python 3.10 or newer. If you've already cloned the repository, change to its folder in PowerShell. To get a new copy, run:

```powershell
git clone https://github.com/amnabun/Data-Processing.git
cd Data-Processing
```

From the repository folder, run:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe build_executable.py
```

The build creates `dist\cw2.exe`. Double-click it in File Explorer or run it from PowerShell:

```powershell
.\dist\cw2.exe
```

The built executable includes its Python dependencies. Close any running copy of `cw2.exe` before rebuilding it.

## Open or import a dataset

- For a raw `.pgn.zst` or `.pgn` file, open **Import games**. Select the source under **Raw games**, choose a `.sqlite` output path under **Save dataset**, then click **Preprocess games**. The app opens the new dataset when the import finishes. You can select a `.pgn.zst` file directly.
- For a `.sqlite` file already created by the app, use **Open processed dataset…**.

With a dataset open, choose **Opening popularity**, **Most improved**, or **Similar players**. The similarity tab has **Time formats** and **Black openings** modes.

## Run from source or use the command line

After installing the dependencies above, this opens the GUI without building the executable:

```powershell
.\.venv\Scripts\python.exe cw2.py
```

To see the command-line options, use either entry point:

```powershell
.\dist\cw2.exe --help
.\.venv\Scripts\python.exe cw2.py --help
```
