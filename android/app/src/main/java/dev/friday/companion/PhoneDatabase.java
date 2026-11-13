package dev.friday.companion;

import androidx.room.Database;
import androidx.room.RoomDatabase;

@Database(entities = {EventRow.class}, version = 1, exportSchema = false)
public abstract class PhoneDatabase extends RoomDatabase {
    public abstract EventDao events();
}
