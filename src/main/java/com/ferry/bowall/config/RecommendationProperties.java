package com.ferry.bowall.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/** 第一版规则推荐的集中实验配置。各质量权重之和建议保持为 1。 */
@Data
@Component
@ConfigurationProperties(prefix = "app.recommendation")
public class RecommendationProperties {
    private String defaultMode = "quality";
    private long smoothingViews = 12;
    private double freshnessHalfLifeHours = 36;
    private double explorationWeight = 0.05;
    private Weights weights = new Weights();

    @Data
    public static class Weights {
        private double dwellQuality = 0.27;
        private double effectiveRead = 0.18;
        private double likeRate = 0.12;
        private double commentRate = 0.10;
        private double lowSkipRate = 0.12;
        private double freshness = 0.14;
        private double authorAffinity = 0.07;
    }
}
