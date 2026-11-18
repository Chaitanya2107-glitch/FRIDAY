package dev.friday.companion

import android.Manifest
import android.content.pm.PackageManager
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import dev.friday.core.SIGNALS
import kotlinx.coroutines.cancel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode
import java.time.Duration

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34, 36], application = CompanionApp::class)
@LooperMode(LooperMode.Mode.PAUSED)
class MainActivityStartupTest {
    @Test fun repositoryDatabaseOpensWithSecureDeletionAndQueueAvailable() {
        val app = ApplicationProvider.getApplicationContext<CompanionApp>()
        try {
            runBlocking(Dispatchers.IO) {
                val db = app.repository.database.openHelper.writableDatabase
                db.query("PRAGMA secure_delete").use { result ->
                    assertTrue(result.moveToFirst())
                    assertEquals(1, result.getInt(0))
                }
                assertTrue(app.repository.commands.rows().isEmpty())
                db.close()
                app.repository.database.openHelper.writableDatabase.query("PRAGMA secure_delete").use { result ->
                    assertTrue(result.moveToFirst())
                    assertEquals(1, result.getInt(0))
                }
            }
        } finally {
            app.repository.scope.cancel()
            app.repository.database.close()
        }
    }

    @Test fun pairedLaunchRendersWithAllOptionalAccessOff() {
        val app = ApplicationProvider.getApplicationContext<CompanionApp>()
        app.repository.settings.paired = true
        val activity = Robolectric.buildActivity(MainActivity::class.java)
        try {
            activity.setup().visible()
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(3))
            assertFalse(activity.get().isFinishing)
            assertFalse(app.repository.sharingRunning)
            assertFalse(app.repository.settings.phoneModes)
            assertFalse(app.repository.settings.notificationSnooze)
        } finally {
            activity.pause().stop().destroy()
            app.repository.scope.cancel()
            app.repository.database.close()
        }
    }

    @Test fun firstLaunchRendersWithoutPairingPermissionsOrCollection() {
        val app = ApplicationProvider.getApplicationContext<CompanionApp>()
        shadowOf(app).denyPermissions(Manifest.permission.CAMERA)
        val activity = Robolectric.buildActivity(MainActivity::class.java)
        try {
            activity.setup().visible()
            shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(3))
            assertFalse(activity.get().isFinishing)
            assertNotNull(activity.get().window.decorView)
            assertFalse(app.repository.settings.paired)
            assertFalse(app.repository.sharingRunning)
            assertTrue(SIGNALS.none { app.repository.settings.enabled(it) })
            assertFalse(app.repository.settings.phoneModes)
            assertFalse(app.repository.settings.notificationSnooze)
            assertEquals(PackageManager.PERMISSION_DENIED, app.checkSelfPermission(Manifest.permission.CAMERA))
        } finally {
            activity.pause().stop().destroy()
            app.repository.scope.cancel()
            app.repository.database.close()
        }
    }
}
