# Train Friday: verify her predictions

Double-click `train_friday.bat` while Friday runs normally. The tool shows saved predictions with their dates and the evidence behind each guess. Press **r** to review them, **l** to refresh pending predictions, **s** to show an ID, or **h** for verification history.

- **Correct** (`c`): reinforce that prediction.
- **Wrong** (`w`): reduce its priority. For an app prediction, optionally name the app you actually opened instead, such as `spotify` or `whatsapp`.
- **Unsure** (`u`) or Enter: keep it pending without training.
- `/stop`: finish the session. Completed verifications are already saved.

There is no approve/apply/train step. Your definite verification immediately adjusts app guesses for the same source app, previous app, hour and weekday/weekend context. Rejected time habits are suppressed while rejections outweigh confirmations. The existing nightly model automatically uses eligible feedback when it has enough activity and evaluation data; the default learning policy still requires a matching observed transition before giving feedback extra model-training weight. This does not fine-tune the chat language model.

Verification applies once per saved prediction, including replies given in normal conversation. It never grants permission to open apps or consumes the live question in another conversation. Historical predictions can be reviewed later; their original time context stays attached. History survives restarts and follows the existing 60-day thought retention.

If the queue is empty, let Friday observe normal app use and make predictions. This tool reviews predictions she has already made; it makes no model or network calls. Previous personal lessons remain stored, but interviews, manual examples, nudge ratings and dataset exports are no longer commands in Train Friday.

Scripted usage:

```powershell
venv/Scripts/python.exe train_friday.py list
venv/Scripts/python.exe train_friday.py show 42
venv/Scripts/python.exe train_friday.py review 42 --verdict correct
venv/Scripts/python.exe train_friday.py review 43 --verdict wrong --actual-app whatsapp
venv/Scripts/python.exe train_friday.py session --count 10
venv/Scripts/python.exe train_friday.py list --state verified
```

Close and reopen an existing Train Friday terminal to load the new interface. Restart Friday from the tray once to load the updated live feedback and ranking code.
