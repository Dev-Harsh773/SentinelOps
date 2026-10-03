package com.sentinelops.mobile.ui.notifications;

import static org.junit.Assert.*;

import com.sentinelops.mobile.data.remote.model.NotificationResponseDTO;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

public class NotificationBatchCountTest {

    @Test
    public void testBatchUnreadCountDerivation() {
        List<NotificationResponseDTO> batch = new ArrayList<>();

        for (int i = 0; i < 10; i++) {
            NotificationResponseDTO n = new NotificationResponseDTO();
            n.notificationId = "notif-" + i;
            n.readStatus = (i < 4) ? "unread" : "read";
            batch.add(n);
        }

        int unreadCount = 0;
        for (NotificationResponseDTO item : batch) {
            if ("unread".equalsIgnoreCase(item.readStatus)) {
                unreadCount++;
            }
        }

        assertEquals(4, unreadCount);
        assertEquals("Unread in loaded batch: 4", "Unread in loaded batch: " + unreadCount);
    }

    @Test
    public void testUnreadFilterSeparation() {
        List<NotificationResponseDTO> batch = new ArrayList<>();
        for (int i = 0; i < 5; i++) {
            NotificationResponseDTO n = new NotificationResponseDTO();
            n.notificationId = "notif-" + i;
            n.readStatus = (i % 2 == 0) ? "unread" : "read";
            batch.add(n);
        }

        List<NotificationResponseDTO> unreadOnly = new ArrayList<>();
        for (NotificationResponseDTO item : batch) {
            if ("unread".equalsIgnoreCase(item.readStatus)) {
                unreadOnly.add(item);
            }
        }

        assertEquals(3, unreadOnly.size()); // indices 0, 2, 4
        for (NotificationResponseDTO item : unreadOnly) {
            assertEquals("unread", item.readStatus);
        }
    }
}
