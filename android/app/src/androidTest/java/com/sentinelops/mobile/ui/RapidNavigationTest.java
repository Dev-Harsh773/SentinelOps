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
public class RapidNavigationTest {

    @Rule
    public ActivityScenarioRule<MainActivity> activityRule =
        new ActivityScenarioRule<>(MainActivity.class);

    @Test
    public void testRapidTabSwitchingDoesNotCrash() {
        int iterations = 4;
        for (int i = 0; i < iterations; i++) {
            onView(withId(R.id.nav_incidents)).perform(click());
            onView(withId(R.id.nav_connectors)).perform(click());
            onView(withId(R.id.nav_notifications)).perform(click());
            onView(withId(R.id.nav_settings)).perform(click());
            onView(withId(R.id.nav_overview)).perform(click());
        }

        // Verify Overview is still properly displayed and alive after rapid switching
        onView(withId(R.id.swipe_refresh)).check(matches(isDisplayed()));
    }
}
