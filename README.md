# ESP Medical Form Downloader

A tool to download and verify MIT ESP's electronic medical forms.


## Usage
### Getting Started
1.  Download the script to your computer

    `git clone https://github.com/btidor/esp-medical.git`

2.  Create a directory to store the downloaded files. This directory should be
    empty and should be on an encrypted partition that is not backed up. (If
    you don't do this, you'll have to securely overwrite the archive and/or
    purge it from backups, later).

3.  Run the script

    `medical.py complete`

### Cross-Check Records with the ESP Website
* `medical.py check`

### Download New Forms
* `medical.py update`


## Archive Format
The archive contains one PDF file per submission. Files are named in the
format: `(id) - (full name) - (username) (version).pdf`

The file `000 - index.txt` contains a listing of all downloaded submissions
and is searchable by any of the above keywords.

The file `config.json` is used internally to persist state.

## Hints
* Don't forget to delete prgram data promplty!
* If you have AFS tokens, `medical.py` will automatically read the requisite
  passwords out of the ESP locker.
* `medical.py` can automatically recover from errors - just run
  `medical.py update` and the script will pick up where it left off.
* Forms should be named in the `[SEASON] PROGRAM YEAR Medical` format.
* When changing the text of the form online, make sure to update
  `template.tex` with the changes, as well.
* When adding or removing questions, update `template.tex` _and_ the
  `REQUIRED_FIELDS` variable in the source code.
