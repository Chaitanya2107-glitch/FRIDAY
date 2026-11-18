package dev.friday.companion;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

@Entity(tableName = "inbox")
public class InboxRow {
    @PrimaryKey @NonNull public String id = "";
    @NonNull public String type = "";
    @NonNull public String payload = "{}";
    public double created;
    public double expiresAt;
    public boolean processed;
}
