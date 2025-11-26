from pathlib import Path
text = Path('templates/AdminSettingsPage.html').read_text(encoding='utf-8')
start = text.index('<div class="subpanel hidden" id="sub-user"')
end = text.index('<div class="subpanel hidden" id="sub-area"')
print(text[start:end])
