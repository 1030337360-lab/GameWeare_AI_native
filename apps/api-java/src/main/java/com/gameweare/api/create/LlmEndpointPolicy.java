package com.gameweare.api.create;

import java.net.InetAddress;
import java.net.URI;
import java.net.UnknownHostException;
import java.util.Arrays;
import java.util.Locale;
import java.util.Set;
import java.util.stream.Collectors;

/** Validates provider names and every DNS answer used by the outbound connector. */
final class LlmEndpointPolicy {
    private final Set<String> allowedHosts;
    private final boolean allowPrivate;

    LlmEndpointPolicy(String allowedHosts, boolean allowPrivate) {
        this.allowedHosts = Arrays.stream(allowedHosts == null ? new String[0] : allowedHosts.split(","))
                .map(String::strip).map(s -> s.toLowerCase(Locale.ROOT))
                .filter(s -> !s.isEmpty()).collect(Collectors.toUnmodifiableSet());
        this.allowPrivate = allowPrivate;
    }

    void validate(URI uri) {
        String host = uri.getHost();
        if (host == null || host.isBlank() || host.endsWith(".") || uri.getRawUserInfo() != null
                || uri.getRawFragment() != null || uri.getRawQuery() != null
                || !("https".equalsIgnoreCase(uri.getScheme())
                    || allowPrivate && "http".equalsIgnoreCase(uri.getScheme())))
            throw new IllegalArgumentException("AI provider URL must use an allowed HTTPS host");
        if (!allowedHosts.isEmpty() && !allowedHosts.contains(host.toLowerCase(Locale.ROOT)))
            throw new IllegalArgumentException("AI provider host is not allowlisted");
    }

    java.util.List<InetAddress> resolve(String host) throws UnknownHostException {
        // OkHttp connects to precisely these returned addresses, avoiding a second unchecked DNS lookup.
        InetAddress[] addresses = InetAddress.getAllByName(host);
        if (addresses.length == 0) throw new UnknownHostException(host);
        if (!allowPrivate) for (InetAddress address : addresses)
            if (!isPublicAddress(address)) throw new UnknownHostException("AI provider address is not public");
        return java.util.List.of(addresses);
    }

    static boolean isPublicAddress(InetAddress address) {
        if (address.isAnyLocalAddress() || address.isLoopbackAddress() || address.isLinkLocalAddress()
                || address.isSiteLocalAddress() || address.isMulticastAddress()) return false;
        byte[] bytes = address.getAddress();
        if (bytes.length == 4) {
            int first = bytes[0] & 255, second = bytes[1] & 255;
            if (first == 0 || first >= 224 || first == 100 && second >= 64 && second <= 127
                    || first == 192 && second == 0 || first == 198 && (second == 18 || second == 19)) return false;
        } else if (bytes.length == 16 && ((bytes[0] & 0xfe) == 0xfc
                || (bytes[0] & 255) == 0x20 && (bytes[1] & 255) == 0x01)) return false;
        return true;
    }
}
