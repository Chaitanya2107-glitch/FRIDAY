package dev.friday.companion;

import androidx.room.Database;
import androidx.room.RoomDatabase;

@Database(entities = {EventRow.class, CommandRow.class, InboxRow.class}, version = 2, exportSchema = false)
public abstract class PhoneDatabase extends RoomDatabase {
    public abstract EventDao events();
    public abstract HandoffDao handoff();
}
