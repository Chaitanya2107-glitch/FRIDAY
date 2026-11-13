package dev.friday.companion;

import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;
import java.util.List;

@Dao
public interface EventDao {
    @Query("SELECT * FROM events ORDER BY timestamp, id") List<EventRow> rows();
    @Insert(onConflict = OnConflictStrategy.REPLACE) void put(EventRow row);
    @Query("DELETE FROM events WHERE id IN (:ids)") void delete(List<String> ids);
    @Query("DELETE FROM events") void clear();
}
