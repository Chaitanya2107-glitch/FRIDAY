package dev.friday.companion

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import dev.friday.core.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)
class RoomBufferTest {
    @Test fun commandAndInboxReceiptsAreDurableAndDeduplicated() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val name = "handoff-test-${java.util.UUID.randomUUID()}.db"
        var db = Room.databaseBuilder(context, PhoneDatabase::class.java, name).allowMainThreadQueries().build()
        try {
            val queue = CommandQueue(RoomCommands(db)) { 1800000000000 }
            val command = queue.add("ring_laptop", buildJsonObject {})
            val message = InboxRow().apply { id = "saved-message-id-123456"; type = "ring"; created = 1800000000.0; expiresAt = created + 900 }
            db.handoff().receive(message); db.handoff().processed(message.id)
            db.close()
            db = Room.databaseBuilder(context, PhoneDatabase::class.java, name).allowMainThreadQueries().build()
            assertEquals(command.id, CommandQueue(RoomCommands(db)) { 1800000000000 }.rows().single().id)
            db.handoff().receive(message)
            assertEquals(1, db.handoff().inbox().size)
            assertTrue(db.handoff().inbox(message.id).processed)
            db.handoff().clearCommands(); db.handoff().clearInbox()
            assertTrue(db.handoff().commands().isEmpty()); assertTrue(db.handoff().inbox().isEmpty())
        } finally { db.close(); context.deleteDatabase(name) }
    }
    @Test fun migrationPreservesVersionOneSignals() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val name = "migration-test-${java.util.UUID.randomUUID()}.db"
        val helper = androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory().create(androidx.sqlite.db.SupportSQLiteOpenHelper.Configuration.builder(context).name(name).callback(object : androidx.sqlite.db.SupportSQLiteOpenHelper.Callback(1) {
            override fun onCreate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE events (id TEXT NOT NULL PRIMARY KEY, timestamp REAL NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL, sentAt INTEGER NOT NULL)")
                db.execSQL("CREATE INDEX index_events_timestamp ON events (timestamp)")
                db.execSQL("CREATE INDEX index_events_sentAt ON events (sentAt)")
                db.execSQL("INSERT INTO events VALUES ('kept',1800000000,'battery','{}',0)")
            }
            override fun onUpgrade(db: androidx.sqlite.db.SupportSQLiteDatabase, old: Int, version: Int) = Unit
        }).build())
        helper.writableDatabase; helper.close()
        val db = Room.databaseBuilder(context, PhoneDatabase::class.java, name).addMigrations(HANDOFF_MIGRATION).allowMainThreadQueries().build()
        try {
            assertEquals("kept", db.events().rows().single().id)
            assertTrue(db.handoff().commands().isEmpty())
            assertTrue(db.handoff().inbox().isEmpty())
        } finally { db.close(); context.deleteDatabase(name) }
    }
    @Test fun actualRoomBufferRetainsPendingAcknowledgesAndForgets() {
        val db = Room.inMemoryDatabaseBuilder(ApplicationProvider.getApplicationContext(), PhoneDatabase::class.java).allowMainThreadQueries().build()
        try {
            var now = 1800000000000L
            val buffer = EventBuffer(RoomStore(db)) { now }
            val policy = object : SharingPolicy {
                override fun enabled(signal: String) = signal == "battery"
                override fun pausedUntil() = 0L
                override fun retentionDays() = 7
                override fun forgetting() = false
            }
            val row = buffer.add("battery", buildJsonObject { put("level", 80); put("charging", true) }, policy)!!
            assertEquals(1, db.events().rows().size)
            assertEquals(row, buffer.pending().single())
            buffer.acknowledge(setOf(row.id)); assertTrue(buffer.pending().isEmpty())
            assertEquals(1, buffer.sentLastHour().size)
            now += 8 * 86400000L; buffer.prune(7); assertTrue(db.events().rows().isEmpty())
            buffer.add("battery", buildJsonObject { put("level", 50); put("charging", false) }, policy)
            buffer.clear(); assertTrue(db.events().rows().isEmpty())
        } finally { db.close() }
    }
}
