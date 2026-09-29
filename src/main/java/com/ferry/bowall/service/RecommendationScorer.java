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

    public RecommendationDetailDto score(Posts post, PostQualityDto quality, int authorAffinity, long authorFanCount,
                                         double averageViews, double averageLikes) {
        long views = quality.getViewCount() == null ? 0 : quality.getViewCount();
        double smoothing = Math.max(1, properties.getSmoothingViews());
        double dwell = smooth(normalizePercent(quality.getDwellScore()), views, 0.50, smoothing);
        double effective = smooth(normalizePercent(quality.getEffectiveReadRate()), views, 0.35, smoothing);
        double likes = smooth(normalizePercent(quality.getLikeRate()), views, 0.04, smoothing);
        double comments = smooth(normalizePercent(quality.getCommentRate()), views, 0.01, smoothing);
        double lowSkip = 1 - smooth(normalizePercent(quality.getQuickSkipRate()), views, 0.35, smoothing);
        double freshness = freshness(post.getUpdateDate());
        double affinity = clamp(authorAffinity / 9.0);
        // 根号压缩让粉丝数和浏览量提供持续曝光优势，却不会无限放大头部账号。
        double audience = saturatingSqrt(authorFanCount, 8.0);
        double heat = relativeSqrt(views, averageViews);
        double trafficPool = trafficPoolScore(views, post.getLikeCount(), averageViews, averageLikes);
        double exploration = deterministicExploration(post.getId());

        RecommendationProperties.Weights weights = properties.getWeights();
        double dwellContribution = dwell * weights.getDwellQuality();
        double effectiveContribution = effective * weights.getEffectiveRead();
        double likeContribution = likes * weights.getLikeRate();
        double commentContribution = comments * weights.getCommentRate();
        double lowSkipContribution = lowSkip * weights.getLowSkipRate();
        double freshnessContribution = freshness * weights.getFreshness();
        double affinityContribution = affinity * weights.getAuthorAffinity();
        double audienceContribution = audience * weights.getAuthorAudience();
        double heatContribution = heat * weights.getGlobalHeat();
        double trafficPoolContribution = trafficPool * weights.getTrafficPool();
        double baseScore = dwellContribution + effectiveContribution + likeContribution + commentContribution
                + lowSkipContribution + freshnessContribution + affinityContribution + audienceContribution + heatContribution
                + trafficPoolContribution;
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
        detail.getComponents().put("authorAudience", round(audience));
        detail.getComponents().put("globalHeat", round(heat));
        detail.getComponents().put("trafficPool", round(trafficPool));
        detail.getComponents().put("exploration", round(exploration));
        detail.getComponents().put("weightedDwellQuality", round(dwellContribution));
        detail.getComponents().put("weightedEffectiveRead", round(effectiveContribution));
        detail.getComponents().put("weightedLikeRate", round(likeContribution));
        detail.getComponents().put("weightedCommentRate", round(commentContribution));
        detail.getComponents().put("weightedLowSkipRate", round(lowSkipContribution));
        detail.getComponents().put("weightedFreshness", round(freshnessContribution));
        detail.getComponents().put("weightedAuthorAffinity", round(affinityContribution));
        detail.getComponents().put("weightedAuthorAudience", round(audienceContribution));
        detail.getComponents().put("weightedGlobalHeat", round(heatContribution));
        detail.getComponents().put("weightedTrafficPool", round(trafficPoolContribution));
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

    private double saturatingSqrt(long value, double scale) {
        return clamp(Math.sqrt(Math.max(0, value)) / scale);
    }

    private double relativeSqrt(long value, double average) {
        return clamp(Math.sqrt(Math.max(0, value) / Math.max(1.0, average)) / 2.0);
    }

    /**
     * 每个候选池按近期候选动态的平均浏览、点赞数据自适应划分：
     * 初始池 10~30，成长池 30~100，放大池 100~500，爆款池 500~1000，再到超级爆款池。
     */
    private double trafficPoolScore(long views, Long likeCount, double averageViews, double averageLikes) {
        long initialLimit = bounded(Math.round(averageViews * .6), 10, 30);
        long growthLimit = Math.max(initialLimit + 1, bounded(Math.round(averageViews * 2), 30, 100));
        long amplificationLimit = Math.max(growthLimit + 1, bounded(Math.round(averageViews * 8), 100, 500));
        long breakoutLimit = Math.max(amplificationLimit + 1, bounded(Math.round(averageViews * 16), 500, 1000));
        double likeRate = views == 0 ? 0 : Math.max(0, likeCount == null ? 0 : likeCount) / (double) views;
        double baselineLikeRate = averageLikes / Math.max(1.0, averageViews);

        if (views < initialLimit) return .72; // 冷启动：所有普通动态均获得首轮测试曝光。
        if (views < growthLimit) return likeRate >= Math.max(.04, baselineLikeRate) ? .82 : .28;
        if (views < amplificationLimit) return likeRate >= Math.max(.06, baselineLikeRate * 1.2) ? .94 : .42;
        if (views < breakoutLimit) return likeRate >= Math.max(.08, baselineLikeRate * 1.4) ? 1.0 : .55;
        return likeRate >= Math.max(.10, baselineLikeRate * 1.6) ? 1.0 : .68;
    }

    private long bounded(long value, long min, long max) {
        return Math.max(min, Math.min(max, value));
    }

    private double clamp(double value) {
        return Math.max(0, Math.min(1, value));
    }

    private double round(double value) {
        return Math.round(value * 10000.0) / 10000.0;
    }
}
