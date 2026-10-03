package com.sentinelops.mobile.ui;

import static androidx.test.espresso.Espresso.onView;
import static androidx.test.espresso.assertion.ViewAssertions.matches;
import static androidx.test.espresso.matcher.ViewMatchers.isDisplayed;
import static androidx.test.espresso.matcher.ViewMatchers.withEffectiveVisibility;
import static androidx.test.espresso.matcher.ViewMatchers.withId;

import androidx.test.espresso.matcher.ViewMatchers;
import androidx.test.ext.junit.rules.ActivityScenarioRule;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import com.sentinelops.mobile.R;
import com.sentinelops.mobile.di.ServiceLocator;
import com.sentinelops.mobile.ui.main.MainActivity;
import org.junit.Rule;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class OfflineBannerSmokeTest {

    @Rule
    public ActivityScenarioRule<MainActivity> activityRule =
        new ActivityScenarioRule<>(MainActivity.class);

    @Test
    public void testOfflineBannerVisibility() {
        activityRule.getScenario().onActivity(activity -> {
            ServiceLocator.getInstance(activity).getBackendHealthRepository().setOnline(false);
        });

        onView(withId(R.id.tv_offline_banner)).check(matches(isDisplayed()));

        activityRule.getScenario().onActivity(activity -> {
            ServiceLocator.getInstance(activity).getBackendHealthRepository().setOnline(true);
        });

        onView(withId(R.id.tv_offline_banner)).check(matches(withEffectiveVisibility(ViewMatchers.Visibility.GONE)));
    }
}
