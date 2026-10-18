package com.sentinelops.mobile.data.local;

import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Token ciphertext is private preferences; the key never leaves Android Keystore. */
public final class OperatorTokenStore {
    private static final String ALIAS = "sentinelops_operator_token";
    private static SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance("AES", "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(ALIAS, null);
    }

    public static synchronized void save(SharedPreferences prefs, String token) {
        if (token.isEmpty()) {
            prefs.edit().remove("operator_ciphertext").remove("operator_iv").apply();
            return;
        }
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            String encrypted = Base64.encodeToString(cipher.doFinal(token.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
            prefs.edit().putString("operator_ciphertext", encrypted)
                .putString("operator_iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP)).apply();
        } catch (Exception error) {
            throw new IllegalStateException("Unable to save operator token securely");
        }
    }

    public static synchronized String read(SharedPreferences prefs) {
        String encrypted = prefs.getString("operator_ciphertext", "");
        if (encrypted.isEmpty()) return "";
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128,
                Base64.decode(prefs.getString("operator_iv", ""), Base64.NO_WRAP)));
            return new String(cipher.doFinal(Base64.decode(encrypted, Base64.NO_WRAP)), StandardCharsets.UTF_8);
        } catch (Exception error) {
            // A restored ciphertext without its device key cannot authenticate.
            return "";
        }
    }
}
