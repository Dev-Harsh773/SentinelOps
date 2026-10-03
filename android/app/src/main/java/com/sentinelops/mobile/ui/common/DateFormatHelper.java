package com.sentinelops.mobile.ui.common;

import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;

public class DateFormatHelper {

    private static final DateTimeFormatter DISPLAY_FORMATTER =
        DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm 'UTC'").withZone(ZoneId.of("UTC"));

    public static String formatIsoUtc(String isoString) {
        if (isoString == null || isoString.trim().isEmpty()) {
            return "N/A";
        }
        try {
            Instant instant = Instant.parse(isoString);
            return DISPLAY_FORMATTER.format(instant);
        } catch (Exception e) {
            return isoString;
        }
    }

    public static String formatRelative(String isoString) {
        if (isoString == null || isoString.trim().isEmpty()) {
            return "";
        }
        try {
            Instant instant = Instant.parse(isoString);
            Instant now = Instant.now();
            long minutes = ChronoUnit.MINUTES.between(instant, now);
            if (minutes < 1) {
                return "just now";
            } else if (minutes < 60) {
                return minutes + "m ago";
            }
            long hours = ChronoUnit.HOURS.between(instant, now);
            if (hours < 24) {
                return hours + "h ago";
            }
            long days = ChronoUnit.DAYS.between(instant, now);
            return days + "d ago";
        } catch (Exception e) {
            return isoString;
        }
    }
}
