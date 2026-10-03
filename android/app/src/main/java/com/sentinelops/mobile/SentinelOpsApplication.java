package com.sentinelops.mobile;

import android.app.Application;
import com.sentinelops.mobile.di.ServiceLocator;

public class SentinelOpsApplication extends Application {

    @Override
    public void onCreate() {
        super.onCreate();
        ServiceLocator.getInstance(this);
    }
}
