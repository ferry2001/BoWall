package com.ferry.bowall.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/** 规则推荐的集中实验配置。各权重之和建议保持为 1。 */
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
        private double dwellQuality = 0.17;
        private double effectiveRead = 0.11;
        private double likeRate = 0.08;
        private double commentRate = 0.06;
        private double lowSkipRate = 0.07;
        private double freshness = 0.09;
        private double authorAffinity = 0.04;
        private double authorAudience = 0.04;
        private double globalHeat = 0.05;
        private double trafficPool = 0.07;
        private double languageMatch = 0.18;
        private double crossLanguageExploration = 0.04;
    }
}
