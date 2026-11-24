# Sweetery — Installation Guide (Windows 10/11)

This guide installs the external tools and Python dependencies needed to run Sweetery locally. Commands are for **PowerShell**. You only need to install the external programs once per computer.

## 1. Install Python

Website: https://www.python.org/downloads/windows/

1. Open the website and find a **Python 3.13.x Windows installer (64-bit)**. Python 3.13 is the version used in Sweetery development; other versions may work but have not been verified for this project.
2. Run the installer. If offered, check **Add python.exe to PATH**, then choose **Install Now**. (The newer Python install manager has a different installation interface; follow its prompts.)
3. Open a **new** PowerShell window and verify:

```powershell
py -3.13 --version
```

If `py` is unavailable, try `python --version`. If neither command works, reopen PowerShell and check the installation instructions on Python.org.

## 2. Install Git

Website: https://git-scm.com/downloads/win

1. Download Git for Windows and run the installer.
2. Default options are generally fine, including Git integration with the command line.
3. Open a new PowerShell window and verify:

```powershell
git --version
```

If you already have the project folder, you do **not** need to clone it again.

## 3. Install Docker Desktop

Website: https://docs.docker.com/desktop/setup/install/windows-install/

1. Read the Windows system requirements on the Docker page. Docker Desktop typically requires hardware virtualization and WSL 2 for the WSL backend.
2. Download **Docker Desktop for Windows** and run the installer.
3. Follow the installer prompts. If asked to enable WSL 2, follow Docker's linked Microsoft instructions; a restart may be required.
4. Open **Docker Desktop** and wait until the Docker engine is running.
5. Open PowerShell and verify:

```powershell
docker --version
docker info
```

`docker --version` checks the command-line tool; `docker info` checks whether the engine is reachable. If `docker info` fails, open Docker Desktop and check that it has finished starting.

## 4. Install and start SearXNG (using Docker)

Official project: https://docs.searxng.org/
Official Docker deployment repository: https://github.com/searxng/searxng-docker
## Searxng
To pull container, run the command: docker run -d --name searxng -p 8080:8080 searxng/searxng

To open the searxng configuration for secret key for .yml file run:
1. docker exec -it searxng sh
2. cat /etc/searxng/settings.yml                      (should see secret key)
3. cd /etc/searxng/                                   (go into directory the .yml key is in)
4. vi settings.yml 
5. change it to look like searxng-settings.yml but make sure your secret key (setp 2) is entered in secret key
5. type exit enter to clear docker setting 
6. start container before running in docker desktop
Note: once this .yml file is edited, you don't have to edit it again!
## 5. Install Ollama and the local AI model

Website: https://ollama.com/download/windows
Model library: https://ollama.com/library/llama3.2

1. Download **Ollama for Windows** and run its installer.
2. Start Ollama if it is not already running.
3. In PowerShell, download the model used by Sweetery:

```powershell
ollama pull llama3.2
```

4. Verify:

```powershell
ollama --version
ollama list
```

5. Optional model test:

```powershell
ollama run llama3.2
```

Type `/bye` to leave the interactive model session. Ensure the model name in your Sweetery configuration matches the installed model. Ollama normally exposes a local API at `http://localhost:11434`.

## 6. Install Tesseract OCR

Tesseract project: https://github.com/tesseract-ocr/tesseract
Windows installer information: https://github.com/UB-Mannheim/tesseract/wiki

1. Open the Tesseract project's Windows installation guidance. For Windows, the project commonly directs users to the **UB Mannheim** builds.
2. Download the appropriate Windows installer from the linked build source and run it.
3. Note the installation directory (commonly `C:\Program Files\Tesseract-OCR`).
4. Add that directory to the Windows **PATH** environment variable if the installer did not do so:
   - Open Start and search **Edit environment variables for your account**.
   - Select **Path** → **Edit** → **New**.
   - Add the directory containing `tesseract.exe` (not the executable filename itself).
   - Save and open a **new** PowerShell window.
5. Verify:

```powershell
tesseract --version
```

If Sweetery's OCR module uses a `SWEETERY_TESSERACT` environment setting, set it to the full path to `tesseract.exe` in your local `.env` file. The exact variable name should match your current `tools/menu_ocr.py` implementation.

## 7. Set up the Sweetery Python environment

1. Open PowerShell in the root folder of the Sweetery project (the folder containing `app.py` and `requirements.txt`).
2. Create a virtual environment with Python 3.13:

```powershell
py -3.13 -m venv .venv
```

3. Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

4. Install the project's dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

5. Install the Chromium browser required by Playwright:

```powershell
python -m playwright install chromium
```

**Note:** `playwright` is a Python package, but Chromium is a separate browser download. Both steps are needed. Python's `venv` module is built in; no `pip install venv` is needed.

If PowerShell blocks activation, you can run the environment's Python directly without changing execution policy:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 9. Make sure you have a .env file. The format should be:

GOOGLE_PLACES_API_KEY=KEYGOESHERE
YELP_API_KEY=KEYGOESHERE
SWEETERY_TESSERACT_CMD=C:\FilePathToTesseractProgramFileHere

## 10. Run tests and launch Sweetery

From the project root, with the virtual environment activated:

```powershell
python -m pytest -q
python -m streamlit run app.py
```

Open the local Streamlit URL printed in PowerShell (commonly `http://localhost:8501`).

## Troubleshooting

- **`streamlit` not recognized:** Activate `.venv` and use `python -m streamlit run app.py`.
- **`No module named playwright`:** Run `python -m pip install -r requirements.txt` in the correct environment; ensure `playwright` is listed in requirements.
- **Playwright browser missing:** Run `python -m playwright install chromium`.
- **`docker info` cannot connect:** Start Docker Desktop and wait for the engine.
- **SearXNG search fails:** Check `docker compose ps`, its logs (`docker compose logs`), the configured URL/port, and whether JSON output is enabled as required by the search integration.
- **Ollama model missing:** Run `ollama pull llama3.2` and check `ollama list`.
- **`tesseract` not recognized:** Fix PATH or set the executable path expected by Sweetery's OCR module.
- **`pip` says `certify` not found:** The package is spelled `certifi`.


##  Google Places API and Yelp Fusion API keys

**These are optional integrations.** If another authorized project member already manages a working key or subscription, you do not need to create another account or purchase another subscription. Ask that member how the application is configured; do not paste keys into GitHub, chat, screenshots, or shared documentation. Only use credentials with the account owner's permission and within the provider's terms and quota.

### Google Maps Platform — Places API (New)

Official setup guide: https://developers.google.com/maps/documentation/places/web-service/get-api-key

Google Cloud Console: https://console.cloud.google.com/

1. Sign in to Google Cloud Console and select or create a project.
2. Review the Places API pricing and billing requirements before enabling anything. Google generally requires a billing-enabled project, even when some usage falls within no-charge allowances.
3. Open **APIs & Services > Library**, find **Places API (New)**, and enable it.
4. Open **Google Maps Platform > Keys & Credentials** and select **Create credentials > API key**, or use an existing authorized key.
5. Restrict the key to the Places API (New) and appropriate application restrictions; configure budgets/alerts and quotas as needed.
6. Store the key in the project's local `.env` file under the **exact variable name required by `config.py`**. Do not commit `.env` to version control.

**If a teammate already has a key:** Use the existing authorized project configuration instead of making a duplicate. A key is associated with a Google Cloud project and billing account; do not assume a personal key is freely shareable.

### Yelp Fusion API

Official getting-started guide: https://docs.developer.yelp.com/docs/getting-started

Yelp developer portal: https://www.yelp.com/developers

1. Read Yelp's Fusion API documentation and check which endpoints and access tier the project needs.
2. Sign in to the developer portal with an appropriate Yelp account.
3. Follow the portal's instructions to create or register an app and request API access, if available for your intended use.
4. Review any plan, quota, billing, and endpoint restrictions before using it. **Do not assume all reviews or endpoints are included with basic access.**
5. Store the API key in `.env` under the exact variable name required by Sweetery's configuration; never commit the key.

