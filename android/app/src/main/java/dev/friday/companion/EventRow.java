package dev.friday.companion;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.Index;
import androidx.room.PrimaryKey;

@Entity(tableName = "events", indices = {@Index("timestamp"), @Index("sentAt")})
public class EventRow {
    @PrimaryKey @NonNull public String id = "";
    public double timestamp;
    @NonNull public String type = "";
    @NonNull public String payload = "{}";
    public long sentAt;
}
