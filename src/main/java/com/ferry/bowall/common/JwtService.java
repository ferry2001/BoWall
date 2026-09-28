package com.ferry.bowall.common;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Minimal HMAC-SHA256 JWT issuer and verifier for the local API.
 * The token only contains the immutable user account and its expiry time.
 */
@Service
public class JwtService {
    private static final Base64.Encoder URL_ENCODER = Base64.getUrlEncoder().withoutPadding();
    private static final Base64.Decoder URL_DECODER = Base64.getUrlDecoder();
    private static final Pattern SUBJECT_PATTERN = Pattern.compile("\\\"sub\\\":\\\"([^\\\"]+)\\\"");
    private static final Pattern EXPIRY_PATTERN = Pattern.compile("\\\"exp\\\":(\\d+)");

    private final byte[] secret;
    private final long expiresSeconds;

    public JwtService(
            @Value("${app.jwt.secret}") String secret,
            @Value("${app.jwt.expires-hours:72}") long expiresHours) {
        this.secret = secret.getBytes(StandardCharsets.UTF_8);
        this.expiresSeconds = expiresHours * 60 * 60;
    }

    public String createToken(String account) {
        long now = Instant.now().getEpochSecond();
        String header = base64Url("{\"alg\":\"HS256\",\"typ\":\"JWT\"}");
        String payload = base64Url("{\"sub\":\"" + account + "\",\"iat\":" + now
                + ",\"exp\":" + (now + expiresSeconds) + "}");
        String unsignedToken = header + "." + payload;
        return unsignedToken + "." + sign(unsignedToken);
    }

    public String parseAccount(String token) {
        String[] parts = token.split("\\.");
        if (parts.length != 3 || !MessageDigest.isEqual(sign(parts[0] + "." + parts[1]).getBytes(StandardCharsets.US_ASCII),
                parts[2].getBytes(StandardCharsets.US_ASCII))) {
            throw new SecurityException("无效 Token");
        }

        String payload = new String(URL_DECODER.decode(parts[1]), StandardCharsets.UTF_8);
        Matcher subject = SUBJECT_PATTERN.matcher(payload);
        Matcher expiry = EXPIRY_PATTERN.matcher(payload);
        if (!subject.find() || !expiry.find() || Long.parseLong(expiry.group(1)) <= Instant.now().getEpochSecond()) {
            throw new SecurityException("Token 已过期");
        }
        return subject.group(1);
    }

    private String sign(String value) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret, "HmacSHA256"));
            return URL_ENCODER.encodeToString(mac.doFinal(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception exception) {
            throw new IllegalStateException("JWT 签名失败", exception);
        }
    }

    private String base64Url(String value) {
        return URL_ENCODER.encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }
}
