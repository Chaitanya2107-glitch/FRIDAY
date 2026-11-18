package dev.friday.companion

import android.app.NotificationManager
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.Shadows.shadowOf
import kotlinx.serialization.json.*

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = CompanionApp::class)
class PresenceControlsTest {
    @Test fun allNewControlsAndVipContentPreferencesStartOff() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("private", Context.MODE_PRIVATE).edit().clear().commit()
        val settings = Settings(context)
        assertFalse(settings.phoneModes); assertFalse(settings.notificationSnooze)
        assertTrue(settings.vipApps.isEmpty()); assertTrue(settings.urgentApps.isEmpty()); assertTrue(settings.contentApps.isEmpty())
        assertTrue(settings.enabledSignals().isEmpty())
    }
    @Test fun policyAccessAndLocalConsentAreBothRequiredForPhoneModes() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("private", Context.MODE_PRIVATE).edit().clear().commit()
        val repo = context.repository
        assertFalse(repo.presence.canControl())
        repo.settings.phoneModes = true
        assertFalse(context.getSystemService(NotificationManager::class.java).isNotificationPolicyAccessGranted)
        assertFalse(repo.presence.canControl())
        val body = buildJsonObject {
            put("mode", "ringer"); put("value", 0); put("token", "a".repeat(32)); put("until", System.currentTimeMillis() / 1000.0 + 60)
        }
        try { repo.presence.mode(body); fail("Unapproved control must not apply") } catch (_: IllegalStateException) { }
        assertTrue(context.getSharedPreferences("presence-controls", Context.MODE_PRIVATE).getString("modes", "[]") == "[]")
        repo.settings.phoneModes = false
    }
    @Test fun modeUndoUsesExactTokenAndDoesNotOverwriteManualChanges() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("private", Context.MODE_PRIVATE).edit().clear().commit()
        context.getSharedPreferences("presence-controls", Context.MODE_PRIVATE).edit().clear().commit()
        val repo = context.repository; val manager = context.getSystemService(NotificationManager::class.java)
        shadowOf(manager).setNotificationPolicyAccessGranted(true)
        manager.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_ALL)
        repo.settings.phoneModes = true; repo.sharingRunning = true; repo.presence.connected()
        fun command(token: String, restore: Boolean = false) = buildJsonObject {
            put("mode", "dnd"); put("value", 2); put("token", token)
            put("until", System.currentTimeMillis() / 1000.0 + 60); put("restore", restore)
        }
        repo.presence.mode(command("a".repeat(32)))
        assertEquals(2, manager.currentInterruptionFilter)
        repo.presence.mode(command("b".repeat(32), true))
        assertEquals(2, manager.currentInterruptionFilter)
        repo.presence.mode(command("a".repeat(32), true))
        assertEquals(1, manager.currentInterruptionFilter)
        repo.presence.mode(command("d".repeat(32)))
        shadowOf(manager).setNotificationPolicyAccessGranted(false)
        repo.presence.mode(command("d".repeat(32), true))
        val pending = Json.parseToJsonElement(context.getSharedPreferences("presence-controls", Context.MODE_PRIVATE).getString("modes", "[]")!!).jsonArray.single().jsonObject
        assertTrue(pending.getValue("until").jsonPrimitive.double <= System.currentTimeMillis() / 1000.0)
        shadowOf(manager).setNotificationPolicyAccessGranted(true)
        repo.presence.restoreAll()
        assertEquals(1, manager.currentInterruptionFilter)
        repo.presence.mode(command("c".repeat(32)))
        manager.setInterruptionFilter(3) // A later owner choice must win.
        repo.presence.mode(command("c".repeat(32), true))
        assertEquals(3, manager.currentInterruptionFilter)
        assertEquals("[]", context.getSharedPreferences("presence-controls", Context.MODE_PRIVATE).getString("modes", "[]"))
    }
}
