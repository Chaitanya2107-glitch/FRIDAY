package dev.friday.companion

import android.app.PendingIntent
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.service.quicksettings.TileService
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

class ShareActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val clipboard = intent.action == "dev.friday.CLIPBOARD"
        val sharedText = if (intent.action == Intent.ACTION_SEND) intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString().orEmpty() else ""
        val file = if (intent.action == Intent.ACTION_SEND) {
            if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
            else { @Suppress("DEPRECATION") intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM) }
        } else null
        setContent { MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFFFFB347))) { Surface(Modifier.fillMaxSize()) {
            var text by remember { mutableStateOf(sharedText) }; var status by remember { mutableStateOf("") }
            var busy by remember { mutableStateOf(false) }; val scope = rememberCoroutineScope()
            Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text("Share to FRIDAY", style = MaterialTheme.typography.headlineMedium)
                Text("Text goes to laptop clipboard history. Links wait for your Open action. Files stay in quarantine and are never opened.")
                if (clipboard) OutlinedButton(onClick = {
                    if (!hasWindowFocus()) { status = "Tap again once this screen is visible."; return@OutlinedButton }
                    val clip = getSystemService(ClipboardManager::class.java).primaryClip
                    // Do not coerce URI content, and never read from a background service.
                    text = if (clip != null && clip.itemCount > 0) clip.getItemAt(0).text?.toString().orEmpty() else ""
                    status = if (text.isEmpty()) "Clipboard contains no plain text." else "Review this text before sending."
                }) { Text("Read current clipboard") }
                if (file != null) Text("Shared file: choose Send to copy it into this app's private waiting buffer. Maximum 100 MB; executable and script names are refused.")
                else OutlinedTextField(text, { text = it }, label = { Text("Text or http(s) link") }, modifier = Modifier.fillMaxWidth(), minLines = 4)
                Text("Safe text waits up to 15 minutes when offline. File transfers expire after 24 hours. Large files are slow because P0's request limits stay active.")
                Button(enabled = !busy && repository.settings.paired && (file != null || text.isNotBlank()), onClick = {
                    busy = true
                    scope.launch {
                        try {
                            withContext(Dispatchers.IO) {
                                if (file != null) Transfers(this@ShareActivity, repository).stage(file)
                                else {
                                    require(text.toByteArray(Charsets.UTF_8).size <= 4000) { "Text must be at most 4,000 bytes" }
                                    repository.handoff.command("phone_handoff", buildJsonObject { put("text", text) })
                                }
                            }
                            status = "Waiting for laptop. Open FRIDAY Companion to view waiting items or start its connection."
                            repository.scope.launch { repository.synchronize() }
                            if (repository.settings.connection) SharingService.start(this@ShareActivity)
                        } catch (failure: Exception) { status = failure.message ?: "Could not share. Pair first and try again." }
                        finally { busy = false }
                    }
                }) { Text(if (busy) "Saving…" else "Send to laptop") }
                Text(status)
                OutlinedButton(onClick = { finish() }) { Text("Close") }
            }
        } } }
    }
}

class ClipboardTile : TileService() {
    override fun onClick() {
        super.onClick()
        val intent = Intent(this, ShareActivity::class.java).setAction("dev.friday.CLIPBOARD").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34) startActivityAndCollapse(PendingIntent.getActivity(this, 73, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
        else openBeforeApi34(intent)
    }
    // The PendingIntent overload does not exist on API29-33; lint ignores this runtime guard.
    @android.annotation.SuppressLint("StartActivityAndCollapseDeprecated")
    @Suppress("DEPRECATION")
    private fun openBeforeApi34(intent: Intent) {
        check(Build.VERSION.SDK_INT < 34)
        startActivityAndCollapse(intent)
    }
}
