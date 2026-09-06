package com.qhkt.search.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data
@Component
@ConfigurationProperties(prefix = "qhkt.interests")
public class InterestsProperties {
    private int topNumber;
}
