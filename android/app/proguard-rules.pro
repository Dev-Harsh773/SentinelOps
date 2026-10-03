# ProGuard rules for SentinelOps Android Client
-keepclassmembers class * {
    @com.google.gson.annotations.SerializedName <fields>;
}
-keep class com.sentinelops.mobile.data.remote.model.** { *; }
