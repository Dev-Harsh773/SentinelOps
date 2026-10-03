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
public class ProjectSelectorUiTest {

    @Rule
    public ActivityScenarioRule<MainActivity> activityRule =
        new ActivityScenarioRule<>(MainActivity.class);

    @Test
    public void testProjectSelectorIsVisibleAndClickable() {
        // Project selector views are displayed in toolbar
        onView(withId(R.id.tv_app_title)).check(matches(isDisplayed()));
        onView(withId(R.id.layout_project_selector)).check(matches(isDisplayed()));
        onView(withId(R.id.tv_selected_project_name)).check(matches(isDisplayed()));
        onView(withId(R.id.iv_project_dropdown)).check(matches(isDisplayed()));

        // Clicking the selector initiates the dialog flow without crashing
        onView(withId(R.id.layout_project_selector)).perform(click());
        try {
            onView(withId(android.R.id.button2)).perform(click());
        } catch (Exception ignored) {
        }

        // Clicking dropdown arrow also initiates the dialog flow without crashing
        onView(withId(R.id.iv_project_dropdown)).perform(click());
        try {
            onView(withId(android.R.id.button2)).perform(click());
        } catch (Exception ignored) {
        }
    }
}
