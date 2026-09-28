package com.ferry.bowall.service;

import com.ferry.bowall.config.RecommendationProperties;
import com.ferry.bowall.dto.PostQualityDto;
import com.ferry.bowall.dto.RecommendationDetailDto;
import com.ferry.bowall.entity.Posts;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;

/** 无机器学习、可解释的规则评分器。 */
@Service
public class RecommendationScorer {
    private final RecommendationProperties properties;

    public RecommendationScorer(RecommendationProperties properties) {
        this.properties = properties;
    }

    public RecommendationDetailDto score(Posts post, PostQualityDto quality, int authorAffinity) {
        long views = quality.getViewCount() == null ? 0 : quality.getViewCount();
        double smoothing = Math.max(1, properties.getSmoothingViews());
        double dwell = smooth(normalizePercent(quality.getDwellScore()), views, 0.50, smoothing);
        double effective = smooth(normalizePercent(quality.getEffectiveReadRate()), views, 0.35, smoothing);
        double likes = smooth(normalizePercent(quality.getLikeRate()), views, 0.04, smoothing);
        double comments = smooth(normalizePercent(quality.getCommentRate()), views, 0.01, smoothing);
        double lowSkip = 1 - smooth(normalizePercent(quality.getQuickSkipRate()), views, 0.35, smoothing);
        double freshness = freshness(post.getUpdateDate());
        double affinity = clamp(authorAffinity / 9.0);
        double exploration = deterministicExploration(post.getId());

        RecommendationProperties.Weights weights = properties.getWeights();
        double dwellContribution = dwell * weights.getDwellQuality();
        double effectiveContribution = effective * weights.getEffectiveRead();
        double likeContribution = likes * weights.getLikeRate();
        double commentContribution = comments * weights.getCommentRate();
        double lowSkipContribution = lowSkip * weights.getLowSkipRate();
        double freshnessContribution = freshness * weights.getFreshness();
        double affinityContribution = affinity * weights.getAuthorAffinity();
        double baseScore = dwellContribution + effectiveContribution + likeContribution + commentContribution
                + lowSkipContribution + freshnessContribution + affinityContribution;
        double explorationBonus = exploration * properties.getExplorationWeight();
        double total = clamp(baseScore + explorationBonus);

        RecommendationDetailDto detail = new RecommendationDetailDto();
        detail.setMode("quality");
        detail.setTotalScore(round(total * 100));
        detail.getComponents().put("dwellQuality", round(dwell));
        detail.getComponents().put("effectiveRead", round(effective));
        detail.getComponents().put("likeRate", round(likes));
        detail.getComponents().put("commentRate", round(comments));
        detail.getComponents().put("lowSkipRate", round(lowSkip));
        detail.getComponents().put("freshness", round(freshness));
        detail.getComponents().put("authorAffinity", round(affinity));
        detail.getComponents().put("exploration", round(exploration));
        detail.getComponents().put("weightedDwellQuality", round(dwellContribution));
        detail.getComponents().put("weightedEffectiveRead", round(effectiveContribution));
        detail.getComponents().put("weightedLikeRate", round(likeContribution));
        detail.getComponents().put("weightedCommentRate", round(commentContribution));
        detail.getComponents().put("weightedLowSkipRate", round(lowSkipContribution));
        detail.getComponents().put("weightedFreshness", round(freshnessContribution));
        detail.getComponents().put("weightedAuthorAffinity", round(affinityContribution));
        detail.getComponents().put("baseScore", round(baseScore));
        detail.getComponents().put("explorationBonus", round(explorationBonus));
        return detail;
    }

    public boolean useTimeMode(String requestedMode) {
        String mode = requestedMode == null || requestedMode.isBlank()
                ? properties.getDefaultMode() : requestedMode;
        return "time".equalsIgnoreCase(mode);
    }

    private double freshness(LocalDateTime publishedAt) {
        if (publishedAt == null) return 0;
        long ageMinutes = Math.max(0, Duration.between(publishedAt, LocalDateTime.now()).toMinutes());
        double halfLifeMinutes = Math.max(1, properties.getFreshnessHalfLifeHours() * 60);
        return Math.pow(0.5, ageMinutes / halfLifeMinutes);
    }

    /** 按帖子与小时生成稳定扰动，刷新同一页不会随机跳动，下一小时会有少量探索变化。 */
    private double deterministicExploration(String postId) {
        long hourBucket = System.currentTimeMillis() / 3_600_000L;
        long hash = 1125899906842597L;
        String key = String.valueOf(postId) + ":" + hourBucket;
        for (int i = 0; i < key.length(); i++) hash = 31 * hash + key.charAt(i);
        return (hash & Long.MAX_VALUE) / (double) Long.MAX_VALUE;
    }

    private double smooth(double observed, long views, double prior, double smoothing) {
        return clamp((observed * Math.max(0, views) + prior * smoothing) / (Math.max(0, views) + smoothing));
    }

    private double normalizePercent(Double value) {
        return clamp((value == null ? 0 : value) / 100.0);
    }

    private double clamp(double value) {
        return Math.max(0, Math.min(1, value));
    }

    private double round(double value) {
        return Math.round(value * 10000.0) / 10000.0;
    }
}
