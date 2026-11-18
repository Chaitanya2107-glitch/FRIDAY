package dev.friday.companion;

import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;
import java.util.List;

@Dao
public interface HandoffDao {
    @Query("SELECT * FROM commands ORDER BY created,rowid") List<CommandRow> commands();
    @Insert(onConflict = OnConflictStrategy.REPLACE) void put(CommandRow row);
    @Query("DELETE FROM commands WHERE id=:id") void removeCommand(String id);
    @Query("DELETE FROM commands WHERE expiresAt<:cutoff AND state!='waiting'") void pruneCommands(double cutoff);
    @Query("SELECT * FROM inbox WHERE id=:id") InboxRow inbox(String id);
    @Query("SELECT * FROM inbox ORDER BY created,id") List<InboxRow> inbox();
    @Insert(onConflict = OnConflictStrategy.IGNORE) void receive(InboxRow row);
    @Query("UPDATE inbox SET processed=1 WHERE id=:id") void processed(String id);
    @Query("DELETE FROM inbox WHERE expiresAt<:cutoff") void pruneInbox(double cutoff);
    @Query("DELETE FROM commands") void clearCommands();
    @Query("DELETE FROM inbox") void clearInbox();
}
