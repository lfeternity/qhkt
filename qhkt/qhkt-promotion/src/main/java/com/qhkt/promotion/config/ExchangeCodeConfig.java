package com.qhkt.promotion.config;

import com.qhkt.promotion.utils.AESUtil;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ExchangeCodeConfig {
    /**
     * 加密密钥，长度必须是256字节
     */
    @Value("${qhkt.promotion.aes.key}")
    private String key;
    /**
     * 初始向量，长度必须是16字节
     */
    @Value("${qhkt.promotion.aes.iv}")
    private String iv;

    @Bean
    public AESUtil aesUtil(){
        return new AESUtil(key, iv);
    }
}
