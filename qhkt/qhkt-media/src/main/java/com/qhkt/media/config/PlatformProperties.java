package com.qhkt.media.config;

import com.qhkt.media.enums.Platform;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data
@Component
@ConfigurationProperties(prefix = "qhkt.platform")
public class PlatformProperties {
    private Platform file;
    private Platform media;
}
