# Writing Assistant for Windows

A small tray app that suggests spelling corrections and word completions locally. Open Review to polish a message with Gemini or generate five alternatives. The app changes text only when you choose a suggestion or click **Apply**.

## Install

**Packaged app** — Open [GitHub Actions](https://github.com/Dhruvkp07/Grammer-Correction-Tool/actions/workflows/windows.yml). After a Windows build succeeds, open the run and download **WritingAssistant-Windows-x64**. Extract the ZIP to a permanent location and run **WritingAssistant.exe** from the extracted folder. Keep the files in that folder together. The executable is unsigned, so Windows may show an unknown publisher prompt.

**From source** — Install [64-bit Python 3.12](https://www.python.org/downloads/windows/) with Tcl/Tk, clone this repository, and run the following in PowerShell.

```powershell
git clone https://github.com/Dhruvkp07/Grammer-Correction-Tool.git
cd Grammer-Correction-Tool
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe app.py
```

To build the standalone folder from source, run `./scripts/build.ps1 -Python ./.venv/Scripts/python.exe`. The output is in `dist/WritingAssistant`. The packaged app includes the Python runtime.

## Set up and use

1. Open **Writing Assistant** and paste your [Google AI Studio API key](https://aistudio.google.com/apikey) into **Gemini API key**. Click **Save settings**. No key is bundled. The model defaults to `gemini-flash-latest`. You can change the model ID if your key requires a different Gemini model.
2. Close Settings to leave the app in the tray. In a supported editor, type an English word and pause briefly. Click the suggested word to apply it, or click **×** to dismiss it.
3. Select some text, then press **Ctrl+Alt+G** or click the floating **Review** button. In a supported single field, you can also review the whole field without selecting text.
4. Check the text shown at the top of the panel. Click **Polish with Gemini** or **Get 5 versions**. The five versions are Professional, Casual, Concise, Friendly, and Direct.
5. Choose a version, then **Apply**, **Copy**, or **Dismiss**. If the original text or selection changed, capture it again or copy the rewrite. For unsupported editors, open **Review** from Settings, paste the text manually, and copy the result back.
6. Click the tray icon to reopen Settings, pause integration, change the shortcut, turn off the spelling overlay or Review button, configure Windows startup, or exit. To replace the key, paste another key and save. Use **Remove API key** to delete it.

## Automatic suggestions

Enable **Auto-polish** in Settings and save once. In a supported editor, type a message and pause for about two seconds. Click the suggested word, polished paragraph, or floating **Apply** button to replace the original text. Apply places the rewrite on your clipboard and pastes it into the verified selection. When a composer blocks paste, the assistant can insert a single-line rewrite by typing it after confirming the original selection is still intact. **3 more** expands inline with Professional, Casual and Concise versions. Click any version to insert it. The separate Review window is available through the shortcut or Settings. If the editor rejects insertion, the overlay shows the reason. Local spelling can suggest **happy** for **happpi**. Auto-polish needs an accessible writable paragraph and at least two words. It sends the current edited paragraph to Gemini after a pause and may use API quota for each changed draft. Turning it off restores manual-only requests.

## Privacy

- Spellchecking uses a local English dictionary. The app inspects the supported focused editor via Windows UI Automation. It does not install a keyboard hook or build a record of typed text.
- Windows-marked password controls are excluded before text access. The app skips focused controls when their password status is unavailable. A custom app must correctly identify its sensitive controls to Windows. Pause editor integration for sensitive work.
- With Auto-polish off, clicking **Polish with Gemini** or **Get 5 versions** sends the displayed text, up to 4,000 characters, to the Gemini API over HTTPS. Requests also include a standard editing instruction, the requested tones, and your key for authentication. No document title, app name, caret context, or spelling data is sent. Google's API terms apply to the submitted text.
- The app does not save reviewed text or results. The API key is encrypted with Windows DPAPI for the current user and stored under `%LOCALAPPDATA%\Writing Assistant`. Settings are stored separately.
- **Copy** and Apply in editors that need a paste replace the current clipboard contents. The app marks these entries to exclude them from Windows clipboard history and cloud sync. Other clipboard tools may still see the current clipboard.

## Compatibility

Windows 10 or 11. Direct capture and replacement depend on the accessibility patterns exposed by the target app. Try standard Windows text controls and browser text inputs first, then your specific mail composer, chat app, or document editor.

| Editor type | How to use it |
| --- | --- |
| Standard text inputs and text areas | Select an excerpt or review the active field. Spelling needs an accessible caret. |
| Rich-text and document editors | Select a continuous excerpt. Direct Apply may use paste and can alter formatting inside the selection. |
| Canvas editors, remote desktops, some chat composers, or elevated windows | Use manual Review and Copy when the app does not expose editable text to Windows UI Automation. |
| Password fields and read-only controls | Passwords are excluded. Read-only text cannot be replaced. |

Caret anchoring is best effort. When an app provides no word bounds, the overlay uses the field bounds. The dictionary suggests common English words, so it may miss uncommon words or multi-letter typos.

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

The tests mock Gemini responses and exercise the guards around editor access and replacement. Windows-only tests cover UI Automation startup, DPAPI key lifecycle, and the real dictionary. On an interactive desktop they also test real capture and replacement in a separate native editor process, plus password-field exclusion. The Windows workflow also smoke-tests the packaged executable. To check live editor integration, try a normal field and a password field in a browser, an editable Notepad document, and your preferred mail or messaging composer. Check that clicking a spelling suggestion changes only the word, moving the selection prevents Apply, and Copy still works in an unsupported editor. To check the live Gemini flow, add your own key and request a polish and five versions for a short test sentence.
