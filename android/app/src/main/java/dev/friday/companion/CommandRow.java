package dev.friday.companion;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

@Entity(tableName = "commands")
public class CommandRow {
    @PrimaryKey @NonNull public String id = "";
    public double created;
    public double expiresAt;
    @NonNull public String command = "";
    @NonNull public String args = "{}";
    @NonNull public String state = "waiting";
    @NonNull public String reply = "{}";
}
