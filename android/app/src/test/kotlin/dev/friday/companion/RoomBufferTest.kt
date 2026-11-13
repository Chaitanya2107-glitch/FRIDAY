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
