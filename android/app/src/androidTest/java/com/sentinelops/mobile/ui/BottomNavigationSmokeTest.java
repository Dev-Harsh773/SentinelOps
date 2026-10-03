package com.sentinelops.mobile.ui;

import static androidx.test.espresso.Espresso.onView;
import static androidx.test.espresso.action.ViewActions.click;
import static androidx.test.espresso.assertion.ViewAssertions.matches;
import static androidx.test.espresso.matcher.ViewMatchers.isDisplayed;
import static androidx.test.espresso.matcher.ViewMatchers.withId;

import androidx.test.ext.junit.rules.ActivityScenarioRule;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import com.sentinelops.mobile.R;
import com.sentinelops.mobile.ui.main.MainActivity;
import org.junit.Rule;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class BottomNavigationSmokeTest {

    @Rule
    public ActivityScenarioRule<MainActivity> activityRule =
        new ActivityScenarioRule<>(MainActivity.class);

    @Test
    public void testOverviewReturnFromEachDestination() {
        // 1. Overview -> Incidents -> Overview
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));
        onView(withId(R.id.nav_incidents)).perform(click());
        onView(withId(R.id.scroll_filters)).check(matches(isDisplayed()));
        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));

        // 2. Overview -> Connectors -> Overview
        onView(withId(R.id.nav_connectors)).perform(click());
        onView(withId(R.id.recycler_connectors)).check(matches(isDisplayed()));
        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));

        // 3. Overview -> Notifications -> Overview
        onView(withId(R.id.nav_notifications)).perform(click());
        onView(withId(R.id.tv_batch_unread_label)).check(matches(isDisplayed()));
        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));

        // 4. Overview -> Settings -> Overview
        onView(withId(R.id.nav_settings)).perform(click());
        onView(withId(R.id.btn_test_connection)).check(matches(isDisplayed()));
        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));
    }

    @Test
    public void testMultiTabSequentialNavigationToOverview() {
        // Overview -> Connectors -> Notifications -> Incidents -> Settings -> Overview
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));

        onView(withId(R.id.nav_connectors)).perform(click());
        onView(withId(R.id.recycler_connectors)).check(matches(isDisplayed()));

        onView(withId(R.id.nav_notifications)).perform(click());
        onView(withId(R.id.tv_batch_unread_label)).check(matches(isDisplayed()));

        onView(withId(R.id.nav_incidents)).perform(click());
        onView(withId(R.id.scroll_filters)).check(matches(isDisplayed()));

        onView(withId(R.id.nav_settings)).perform(click());
        onView(withId(R.id.btn_test_connection)).check(matches(isDisplayed()));

        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));
    }

    @Test
    public void testRepeatedNavigationDoesNotDuplicateOrCrash() {
        // Overview -> Incidents -> Overview -> Incidents -> Overview
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));

        onView(withId(R.id.nav_incidents)).perform(click());
        onView(withId(R.id.scroll_filters)).check(matches(isDisplayed()));

        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));

        onView(withId(R.id.nav_incidents)).perform(click());
        onView(withId(R.id.scroll_filters)).check(matches(isDisplayed()));

        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));
    }

    @Test
    public void testOverviewCardShortcutsNavigateAndReturnViaBottomNav() {
        // 1. Overview cardIncidents shortcut -> Incidents -> Bottom-Nav Overview
        onView(withId(R.id.card_incidents)).perform(click());
        onView(withId(R.id.scroll_filters)).check(matches(isDisplayed()));
        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));

        // 2. Overview cardConnectors shortcut -> Connectors -> Bottom-Nav Overview
        onView(withId(R.id.card_connectors)).perform(click());
        onView(withId(R.id.recycler_connectors)).check(matches(isDisplayed()));
        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));

        // 3. Overview cardNotifications shortcut -> Notifications -> Bottom-Nav Overview
        onView(withId(R.id.card_notifications)).perform(click());
        onView(withId(R.id.tv_batch_unread_label)).check(matches(isDisplayed()));
        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));
    }

    @Test
    public void testReselectionOfActiveTabIsSafeNoOp() {
        // Reselect Overview while on Overview
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));
        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));

        // Reselect Incidents while on Incidents
        onView(withId(R.id.nav_incidents)).perform(click());
        onView(withId(R.id.scroll_filters)).check(matches(isDisplayed()));
        onView(withId(R.id.nav_incidents)).perform(click());
        onView(withId(R.id.scroll_filters)).check(matches(isDisplayed()));

        // Return to Overview
        onView(withId(R.id.nav_overview)).perform(click());
        onView(withId(R.id.card_incidents)).check(matches(isDisplayed()));
    }
}
