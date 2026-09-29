package com.ferry.bowall.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ferry.bowall.common.R;
import com.ferry.bowall.dto.CommentsDto;
import com.ferry.bowall.dto.PostQualityDto;
import com.ferry.bowall.dto.PostsDto;
import com.ferry.bowall.dto.RecommendationDetailDto;
import com.ferry.bowall.entity.*;
import com.ferry.bowall.enums.Comments.CommentsIsDel;
import com.ferry.bowall.filter.JwtAuthInterceptor;
import com.ferry.bowall.service.*;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@RequestMapping("/posts")
@RestController
@Slf4j
public class PostsController {

    private static final long MAX_DWELL_SECONDS_PER_REPORT = 300;
    private static final long MAX_DWELL_SECONDS_PER_POST_SESSION = 1800;
    private static final long MAX_DWELL_SECONDS_FOR_QUALITY = 300;

    @Autowired
    private PostsService postsService;

    @Autowired
    private UserService userService;

    @Autowired
    private ImageService imageService;

    @Autowired
    private CommentsService commentsService;

    @Autowired
    private LikeService likeService;

    @Autowired
    private FollowersService followersService;

    @Autowired
    private FansService fansService;

    @Autowired
    private PostDwellService postDwellService;

    @Autowired
    private RecommendationScorer recommendationScorer;

    /**
     * 由前端在动态卡片进入视区时调用。浏览数只记录展示行为，前端会在单次页面会话中去重。
     */
    @PostMapping("/{postId}/view")
    public R<Long> recordView(@PathVariable String postId) {
        Posts post = postsService.getById(postId);
        if (post == null) return R.error("动态不存在");
        postsService.update(new LambdaUpdateWrapper<Posts>()
                .eq(Posts::getId, postId)
                .setSql("view_count = COALESCE(view_count, 0) + 1"));
        return R.success((post.getViewCount() == null ? 0 : post.getViewCount()) + 1);
    }

    /**
     * 将前端在“可视面积至少 55% 且页面处于前台”期间累计的停留时间写入当前会话。
     * 每个上报片段最多五分钟，每条动态在同一会话最多计三十分钟，防止后台挂起等异常值污染统计。
     */
    @PostMapping("/{postId}/dwell")
    public R<Long> recordDwell(HttpServletRequest request, @PathVariable String postId, @RequestBody Map<String, Object> payload) {
        Posts post = postsService.getById(postId);
        if (post == null) return R.error("动态不存在");

        String account = (String) request.getAttribute(JwtAuthInterceptor.CURRENT_ACCOUNT);
        String sessionId = String.valueOf(payload.getOrDefault("sessionId", "")).trim();
        if (sessionId.isEmpty() || sessionId.length() > 64) return R.error("浏览会话无效");

        long reportedSeconds;
        try {
            reportedSeconds = Long.parseLong(String.valueOf(payload.getOrDefault("seconds", 0)));
        } catch (NumberFormatException exception) {
            return R.error("停留时长无效");
        }
        if (reportedSeconds <= 0) return R.success(0L);
        reportedSeconds = Math.min(reportedSeconds, MAX_DWELL_SECONDS_PER_REPORT);

        LambdaQueryWrapper<PostDwell> query = new LambdaQueryWrapper<PostDwell>()
                .eq(PostDwell::getPostId, postId)
                .eq(PostDwell::getAccount, account)
                .eq(PostDwell::getSessionId, sessionId);
        PostDwell dwell = postDwellService.getOne(query);
        if (dwell == null) {
            dwell = new PostDwell();
            dwell.setId(UUID.randomUUID().toString());
            dwell.setPostId(postId);
            dwell.setAccount(account);
            dwell.setSessionId(sessionId);
            dwell.setDwellSeconds(Math.min(reportedSeconds, MAX_DWELL_SECONDS_PER_POST_SESSION));
            dwell.setUpdateDate(LocalDateTime.now());
            postDwellService.save(dwell);
        } else {
            long currentSeconds = dwell.getDwellSeconds() == null ? 0 : dwell.getDwellSeconds();
            long acceptedSeconds = Math.min(reportedSeconds, Math.max(0, MAX_DWELL_SECONDS_PER_POST_SESSION - currentSeconds));
            if (acceptedSeconds > 0) {
                dwell.setDwellSeconds(currentSeconds + acceptedSeconds);
                dwell.setUpdateDate(LocalDateTime.now());
                postDwellService.updateById(dwell);
            }
        }
        return R.success(dwell.getDwellSeconds());
    }

    /**
     * 质量指标只供动态作者查看。它读取浏览、停留、点赞和评论数据，但不会影响推荐排序。
     */
    @GetMapping("/{postId}/quality")
    public R<PostQualityDto> quality(HttpServletRequest request, @PathVariable String postId) {
        Posts post = postsService.getById(postId);
        if (post == null) return R.error("动态不存在");
        String currentAccount = (String) request.getAttribute(JwtAuthInterceptor.CURRENT_ACCOUNT);
        if (!post.getAccount().equals(currentAccount)) return R.error("只能查看自己的动态数据");

        return R.success(buildPostQuality(post));
    }

    private PostQualityDto buildPostQuality(Posts post) {
        String postId = post.getId();
        long imageCount = imageService.count(new LambdaQueryWrapper<Image>().eq(Image::getPostsId, postId));
        long expectedSeconds = estimateExpectedDwellSeconds(post.getText(), imageCount);
        long effectiveThreshold = Math.max(3, Math.round(expectedSeconds * 0.5));
        long quickSkipThreshold = Math.min(5, Math.max(2, Math.round(expectedSeconds * 0.2)));
        long qualityCap = Math.min(MAX_DWELL_SECONDS_FOR_QUALITY, Math.max(60, expectedSeconds * 3));

        List<Long> recordedDwell = postDwellService.list(new LambdaQueryWrapper<PostDwell>()
                        .eq(PostDwell::getPostId, postId))
                .stream()
                .map(item -> Math.min(item.getDwellSeconds() == null ? 0 : item.getDwellSeconds(), qualityCap))
                .sorted()
                .toList();

        long storedViewCount = post.getViewCount() == null ? 0 : post.getViewCount();
        long totalViews = Math.max(storedViewCount, recordedDwell.size());
        long totalDwell = recordedDwell.stream().mapToLong(Long::longValue).sum();
        long effectiveReads = recordedDwell.stream().filter(seconds -> seconds >= effectiveThreshold).count();
        long zeroDwellViews = Math.max(0, totalViews - recordedDwell.size());
        long quickSkips = zeroDwellViews + recordedDwell.stream().filter(seconds -> seconds < quickSkipThreshold).count();
        long likeCount = post.getLikeCount() == null ? 0 : post.getLikeCount();
        long commentCount = commentsService.count(new LambdaQueryWrapper<Comments>()
                .eq(Comments::getPostsId, postId)
                .eq(Comments::getIsDel, CommentsIsDel.no));

        PostQualityDto dto = new PostQualityDto();
        dto.setPostId(postId);
        dto.setViewCount(totalViews);
        dto.setRecordedSessionCount((long) recordedDwell.size());
        dto.setExpectedDwellSeconds(expectedSeconds);
        dto.setEffectiveReadThresholdSeconds(effectiveThreshold);
        dto.setQuickSkipThresholdSeconds(quickSkipThreshold);
        dto.setEffectiveReadRate(percent(effectiveReads, totalViews));
        dto.setQuickSkipRate(percent(quickSkips, totalViews));
        dto.setAverageDwellSeconds(round(totalViews == 0 ? 0 : (double) totalDwell / totalViews));
        dto.setMedianDwellSeconds(round(medianWithImplicitZero(recordedDwell, totalViews)));
        dto.setLikeRate(percent(likeCount, totalViews));
        dto.setCommentRate(percent(commentCount, totalViews));
        dto.setDwellScore(round(Math.min(100, totalViews == 0 ? 0 : ((double) totalDwell / totalViews) / expectedSeconds * 100)));
        return dto;
    }

    private long estimateExpectedDwellSeconds(String text, long imageCount) {
        int characters = text == null ? 0 : text.codePointCount(0, text.length());
        long textSeconds = (long) Math.ceil(characters / 12.0);
        return Math.min(90, Math.max(3, 3 + textSeconds + imageCount * 4));
    }

    private double medianWithImplicitZero(List<Long> sortedDwell, long totalViews) {
        if (totalViews <= 0) return 0;
        long zeroCount = Math.max(0, totalViews - sortedDwell.size());
        long left = valueAt(sortedDwell, zeroCount, (totalViews - 1) / 2);
        long right = valueAt(sortedDwell, zeroCount, totalViews / 2);
        return (left + right) / 2.0;
    }

    private long valueAt(List<Long> sortedDwell, long zeroCount, long index) {
        return index < zeroCount ? 0 : sortedDwell.get((int) (index - zeroCount));
    }

    private double percent(long numerator, long denominator) {
        return round(denominator == 0 ? 0 : Math.min(100, numerator * 100.0 / denominator));
    }

    private double round(double value) {
        return Math.round(value * 10.0) / 10.0;
    }

    @GetMapping("getPostsById")
    public R<PostsDto> getPostsById(@RequestParam String postId) {
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper.eq(Posts::getId, postId);
        Posts post = postsService.getOne(postsLambdaQueryWrapper);

        LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        imageLambdaQueryWrapper.eq(Image::getPostsId, post.getId());
        List<Image> images = imageService.list(imageLambdaQueryWrapper);

        //select user object in post
        User user = userService.getUser(post.getAccount());

        //select commentsDto object in post
        //1.select comments 2.new arraylist of commentsDto
        //3.for comments which add name of commenter and comment into commentsDto
        LambdaQueryWrapper<Comments> commentsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        commentsLambdaQueryWrapper = commentsLambdaQueryWrapper.eq(Comments::getPostsId, post.getId());
        List<Comments> comments = commentsService.list(commentsLambdaQueryWrapper);
        ArrayList<CommentsDto> commentsDtos = new ArrayList<>();
        for (Comments comment : comments) {
            CommentsDto commentsDto = new CommentsDto();
            commentsDto.setComments(comment);

            String commentUserName = userService.getUserName(comment.getAccount());
            String commentUserAvatar = userService.getUserAvatar(comment.getAccount());
            commentsDto.setName(commentUserName);
            commentsDto.setUserAvatar(commentUserAvatar);
            if (comment.getReplyToAccount() != null && !comment.getReplyToAccount().isBlank()) {
                commentsDto.setReplyToName(userService.getUserName(comment.getReplyToAccount()));
            }

            commentsDtos.add(commentsDto);
        }

        PostsDto postsDto = new PostsDto();
        postsDto.setUser(user);
        postsDto.setAccount(post.getAccount());
        postsDto.setId(post.getId());
        postsDto.setText(post.getText());
        postsDto.setViewCount(post.getViewCount());
        postsDto.setUpdateDate(post.getUpdateDate());
        postsDto.setImages(images);
        postsDto.setComments(commentsDtos);
        LambdaQueryWrapper<Likes> likesCountWrapper = new LambdaQueryWrapper<>();
        likesCountWrapper.eq(Likes::getPostId, post.getId());
        postsDto.setLikeCount(likeService.count(likesCountWrapper));

        return R.success(postsDto);
    }

    @GetMapping("/getAllPosts")
    public R<List<PostsDto>> getAllPosts(
            @RequestParam int page,
            @RequestParam int size,
            @RequestParam String account,
            @RequestParam(required = false) String excludeIds) {
        List<PostsDto> postsDtos = new ArrayList<>();
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        // 精品优先；同一层级内仍按最新动态排序，保持旧客户端的时间线预期。
        postsLambdaQueryWrapper.orderByDesc(Posts::getIsFeatured)
                .orderByDesc(Posts::getUpdateDate);
        // 浏览记录来自客户端，不信任其长度或空项，最多接收 500 个 ID。
        if (excludeIds != null && !excludeIds.isBlank()) {
            LinkedHashSet<String> excluded = new LinkedHashSet<>();
            for (String candidate : excludeIds.split(",")) {
                String postId = candidate.trim();
                if (!postId.isEmpty()) excluded.add(postId);
                if (excluded.size() >= 500) break;
            }
            if (!excluded.isEmpty()) postsLambdaQueryWrapper.notIn(Posts::getId, excluded);
        }
//        List<Posts> posts = postsService.list(postsLambdaQueryWrapper);
        Page<Posts> postsPage = new Page<>(page, size);
        postsPage = postsService.page(postsPage, postsLambdaQueryWrapper);
        List<Posts> posts = postsPage.getRecords();
        for (Posts post : posts) {
            // select images object in post
            LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
            imageLambdaQueryWrapper.eq(Image::getPostsId, post.getId());
            List<Image> images = imageService.list(imageLambdaQueryWrapper);

            //select user object in post
            User user = userService.getUser(post.getAccount());

            //select commentsDto object in post
            //1.select comments 2.new arraylist of commentsDto
            //3.for comments which add name of commenter and comment into commentsDto
            LambdaQueryWrapper<Comments> commentsLambdaQueryWrapper = new LambdaQueryWrapper<>();
            commentsLambdaQueryWrapper = commentsLambdaQueryWrapper.eq(Comments::getPostsId, post.getId());
            commentsLambdaQueryWrapper.orderByAsc(Comments::getUpdateDate);
            List<Comments> comments = commentsService.list(commentsLambdaQueryWrapper);
            ArrayList<CommentsDto> commentsDtos = new ArrayList<>();
            for (Comments comment : comments) {
                CommentsDto commentsDto = new CommentsDto();
                commentsDto.setComments(comment);

                String commentUserName = userService.getUserName(comment.getAccount());
                String commentUserAvatar = userService.getUserAvatar(comment.getAccount());
                commentsDto.setName(commentUserName);
                commentsDto.setUserAvatar(commentUserAvatar);
                if (comment.getReplyToAccount() != null && !comment.getReplyToAccount().isBlank()) {
                    commentsDto.setReplyToName(userService.getUserName(comment.getReplyToAccount()));
                }

                commentsDtos.add(commentsDto);
            }

            LambdaQueryWrapper<Likes> likesLambdaQueryWrapper = new LambdaQueryWrapper<Likes>();
            likesLambdaQueryWrapper.eq(Likes::getAccount,account)
                    .eq(Likes::getPostId,post.getId());
            Likes likes = likeService.getOne(likesLambdaQueryWrapper);
            PostsDto postsDto = new PostsDto();
            postsDto.setUser(user);
            postsDto.setAccount(post.getAccount());
            postsDto.setId(post.getId());
            postsDto.setText(post.getText());
            postsDto.setViewCount(post.getViewCount());
            postsDto.setIsFeatured(post.getIsFeatured());
            postsDto.setUpdateDate(post.getUpdateDate());
            postsDto.setImages(images);
            postsDto.setComments(commentsDtos);
            if (likes == null) {
                postsDto.setIsLike(0);
            }else {
                postsDto.setIsLike(1);
            }
            LambdaQueryWrapper<Likes> likesCountWrapper = new LambdaQueryWrapper<>();
            likesCountWrapper.eq(Likes::getPostId, post.getId());
            postsDto.setLikeCount(likeService.count(likesCountWrapper));
            postsDtos.add(postsDto);
        }


        return R.success(postsDtos);
    }

    /**
     * 首页推荐：基于阅读质量、互动反馈、作者关联度和新鲜度的可解释规则评分。
     * 传 mode=time 或修改配置即可回退为纯时间倒序。
     */
    @GetMapping("/recommendations")
    public R<List<PostsDto>> recommendations(
            @RequestParam String account,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String mode,
            @RequestParam(required = false) String excludeIds) {
        int safePage = Math.max(page, 1);
        int safeSize = Math.min(Math.max(size, 1), 50);
        Map<String, Integer> authorAffinity = new java.util.HashMap<>();

        LambdaQueryWrapper<Followers> followingQuery = new LambdaQueryWrapper<>();
        followingQuery.eq(Followers::getAccount, account);
        for (Followers following : followersService.list(followingQuery)) {
            authorAffinity.merge(following.getFollowersAccount(), 6, Integer::sum);
        }

        List<String> interactedPostIds = new ArrayList<>();
        LambdaQueryWrapper<Likes> likesQuery = new LambdaQueryWrapper<>();
        likesQuery.eq(Likes::getAccount, account);
        interactedPostIds.addAll(likeService.list(likesQuery).stream()
                .map(Likes::getPostId)
                .toList());

        LambdaQueryWrapper<Comments> commentsQuery = new LambdaQueryWrapper<>();
        commentsQuery.eq(Comments::getAccount, account);
        interactedPostIds.addAll(commentsService.list(commentsQuery).stream()
                .map(Comments::getPostsId)
                .toList());

        if (!interactedPostIds.isEmpty()) {
            LambdaQueryWrapper<Posts> interactedPostsQuery = new LambdaQueryWrapper<>();
            interactedPostsQuery.in(Posts::getId, new LinkedHashSet<>(interactedPostIds));
            for (Posts interactedPost : postsService.list(interactedPostsQuery)) {
                if (!account.equals(interactedPost.getAccount())) {
                    authorAffinity.merge(interactedPost.getAccount(), 3, Integer::sum);
                }
            }
        }

        // 多取一些候选后在内存中进行规则评分；异常时保留时间流作为兜底。
        LambdaQueryWrapper<Posts> candidateQuery = new LambdaQueryWrapper<>();
        candidateQuery.ne(Posts::getAccount, account);
        if (excludeIds != null && !excludeIds.isBlank()) {
            LinkedHashSet<String> excluded = new LinkedHashSet<>();
            for (String candidate : excludeIds.split(",")) {
                String postId = candidate.trim();
                if (!postId.isEmpty()) excluded.add(postId);
                if (excluded.size() >= 500) break;
            }
            if (!excluded.isEmpty()) candidateQuery.notIn(Posts::getId, excluded);
        }
        candidateQuery
                .orderByDesc(Posts::getUpdateDate);
        List<Posts> candidates = postsService.page(new Page<>(1, 500), candidateQuery).getRecords();
        double averageViews = candidates.stream()
                .mapToLong(post -> post.getViewCount() == null ? 0 : post.getViewCount())
                .average().orElse(0);
        double averageLikes = candidates.stream()
                .mapToLong(post -> post.getLikeCount() == null ? 0 : post.getLikeCount())
                .average().orElse(0);
        Map<String, Long> authorFanCounts = new java.util.HashMap<>();
        LinkedHashSet<String> authorAccounts = new LinkedHashSet<>();
        for (Posts candidate : candidates) {
            if (candidate.getAccount() != null && !candidate.getAccount().isBlank()) {
                authorAccounts.add(candidate.getAccount());
            }
        }
        if (!authorAccounts.isEmpty()) {
            LambdaQueryWrapper<Fans> fansQuery = new LambdaQueryWrapper<>();
            fansQuery.in(Fans::getAccount, authorAccounts);
            for (Fans fan : fansService.list(fansQuery)) {
                authorFanCounts.merge(fan.getAccount(), 1L, Long::sum);
            }
        }
        Map<String, RecommendationDetailDto> scoreDetails = new java.util.HashMap<>();
        boolean timeMode = recommendationScorer.useTimeMode(mode);
        if (!timeMode) {
            try {
                for (Posts post : candidates) {
                    scoreDetails.put(post.getId(), recommendationScorer.score(
                            post, buildPostQuality(post), authorAffinity.getOrDefault(post.getAccount(), 0),
                            authorFanCounts.getOrDefault(post.getAccount(), 0L), averageViews, averageLikes));
                }
                candidates.sort((left, right) -> {
                    int scoreCompare = Double.compare(
                            scoreDetails.get(right.getId()).getTotalScore(), scoreDetails.get(left.getId()).getTotalScore());
                    return scoreCompare != 0 ? scoreCompare : right.getUpdateDate().compareTo(left.getUpdateDate());
                });
            } catch (Exception exception) {
                // 指标数据异常时，直接回退到时间流，首页仍可用。
                log.warn("推荐评分失败，回退到时间排序", exception);
                scoreDetails.clear();
                timeMode = true;
            }
        }
        if (timeMode) {
            candidates.sort((left, right) -> right.getUpdateDate().compareTo(left.getUpdateDate()));
        } else if (safePage == 1) {
            candidates.stream().limit(5).forEach(post -> {
                RecommendationDetailDto detail = scoreDetails.get(post.getId());
                log.info("推荐明细 post={} score={} components={}", post.getId(), detail.getTotalScore(), detail.getComponents());
            });
        }

        int start = (safePage - 1) * safeSize;
        List<PostsDto> recommendations = new ArrayList<>();
        for (Posts post : candidates.stream().skip(start).limit(safeSize).toList()) {
            LambdaQueryWrapper<Image> imageQuery = new LambdaQueryWrapper<>();
            imageQuery.eq(Image::getPostsId, post.getId());

            PostsDto dto = new PostsDto();
            dto.setUser(userService.getUser(post.getAccount()));
            dto.setAccount(post.getAccount());
            dto.setId(post.getId());
            dto.setText(post.getText());
            dto.setViewCount(post.getViewCount());
            dto.setIsFeatured(post.getIsFeatured());
            dto.setUpdateDate(post.getUpdateDate());
            dto.setImages(imageService.list(imageQuery));

            // 首页推荐与普通动态流使用同一套评论数据，避免推荐卡片只显示点赞而漏掉讨论内容。
            LambdaQueryWrapper<Comments> commentQuery = new LambdaQueryWrapper<>();
            commentQuery.eq(Comments::getPostsId, post.getId())
                    .orderByAsc(Comments::getUpdateDate);
            ArrayList<CommentsDto> commentDtos = new ArrayList<>();
            for (Comments comment : commentsService.list(commentQuery)) {
                CommentsDto commentDto = new CommentsDto();
                commentDto.setComments(comment);
                commentDto.setName(userService.getUserName(comment.getAccount()));
                commentDto.setUserAvatar(userService.getUserAvatar(comment.getAccount()));
                if (comment.getReplyToAccount() != null && !comment.getReplyToAccount().isBlank()) {
                    commentDto.setReplyToName(userService.getUserName(comment.getReplyToAccount()));
                }
                commentDtos.add(commentDto);
            }
            dto.setComments(commentDtos);

            LambdaQueryWrapper<Likes> currentLikeQuery = new LambdaQueryWrapper<>();
            currentLikeQuery.eq(Likes::getAccount, account)
                    .eq(Likes::getPostId, post.getId());
            dto.setIsLike(likeService.getOne(currentLikeQuery) == null ? 0 : 1);

            dto.setLikeCount(post.getLikeCount() == null ? 0 : post.getLikeCount());
            dto.setRecommendation(scoreDetails.get(post.getId()));
            recommendations.add(dto);
        }
        return R.success(recommendations);
    }

    @PostMapping("/post")
    public R<String> post(@RequestBody Map map) {
        Posts posts = new Posts();
        String account = map.get("account").toString();
        String text = map.get("text").toString();
        UUID uuid = UUID.randomUUID();

        posts.setAccount(account);
        posts.setId(uuid.toString());
        posts.setText(text);
        posts.setLikeCount(0L);
        posts.setUpdateDate(LocalDateTime.now());

        postsService.save(posts);
        return R.success(uuid.toString());
    }

    @PostMapping("/forward")
    public R<String> forward(@RequestBody Map map) {
        String account = map.get("account").toString();
        String postId = map.get("postId").toString();
        List list = (List) map.get("images");

        UUID uuid = UUID.randomUUID();
        Posts post = postsService.getById(postId);
        Posts posts = new Posts();
        posts.setAccount(account);
        posts.setId(uuid.toString());
        posts.setText("转发来自用户账号为@"+post.getAccount()+"的动态:"+post.getText());
        posts.setLikeCount(0L);
        posts.setUpdateDate(LocalDateTime.now());
        postsService.save(posts);
        for (Object o : list) {
            Map mapImage = (Map) o;
            System.out.println(mapImage.get("url").toString());
            String url = mapImage.get("url").toString();
            String width = mapImage.get("width").toString();
            String height = mapImage.get("height").toString();

            Image image = new Image();
            image.setAccount(account);
            image.setUrl(url);
            image.setPostsId(uuid.toString());
            image.setWidth(width);
            image.setHeight(height);
            image.setUpdateDate(LocalDateTime.now());
            imageService.save(image);

        }


        return null;
    }

    @GetMapping("/getPosts")
    public R<List<PostsDto>> getPosts(@RequestParam String account) {
        List<PostsDto> postsDtos = new ArrayList<>();
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper = postsLambdaQueryWrapper.in(Posts::getAccount, account);
        List<Posts> posts = postsService.list(postsLambdaQueryWrapper);

        for (Posts post : posts) {
            LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
            imageLambdaQueryWrapper = imageLambdaQueryWrapper.eq(Image::getPostsId, post.getId());
            List<Image> images = imageService.list(imageLambdaQueryWrapper);

            PostsDto postsDto = new PostsDto();
            postsDto.setAccount(post.getAccount());
            postsDto.setId(post.getId());
            postsDto.setText(post.getText());
            postsDto.setViewCount(post.getViewCount());
            postsDto.setUpdateDate(post.getUpdateDate());
            postsDto.setImages(images);
            LambdaQueryWrapper<Likes> likesCountWrapper = new LambdaQueryWrapper<>();
            likesCountWrapper.eq(Likes::getPostId, post.getId());
            postsDto.setLikeCount(likeService.count(likesCountWrapper));

            postsDtos.add(postsDto);
        }

        return R.success(postsDtos);
    }

    /**
     * get pages of posts
     *
     * @param page
     * @param size
     * @param inValue
     * @return
     */
    @GetMapping("/getPostsPages")
    public R<List<PostsDto>> getPostsPages(
            @RequestParam int page,
            @RequestParam int size,
            @RequestParam String inValue,
            @RequestParam(required = false) String account) {
        String keyword = inValue == null ? "" : inValue.trim();
        if (keyword.isEmpty()) {
            return R.success(new ArrayList<>());
        }

        // 昵称命中的用户，其全部动态也应当出现在搜索结果中；账号与正文则直接模糊匹配。
        LambdaQueryWrapper<User> userQuery = new LambdaQueryWrapper<>();
        userQuery.like(User::getAccount, keyword)
                .or()
                .like(User::getName, keyword);
        LinkedHashSet<String> matchedAccounts = userService.list(userQuery).stream()
                .map(User::getAccount)
                .collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));

        LambdaQueryWrapper<Posts> postQuery = new LambdaQueryWrapper<>();
        postQuery.nested(query -> query.like(Posts::getText, keyword)
                .or()
                .like(Posts::getAccount, keyword));
        if (!matchedAccounts.isEmpty()) {
            postQuery.or(query -> query.in(Posts::getAccount, matchedAccounts));
        }
        postQuery.orderByDesc(Posts::getUpdateDate);

        int safePage = Math.max(page, 1);
        int safeSize = Math.min(Math.max(size, 1), 50);
        List<Posts> posts = postsService.page(new Page<>(safePage, safeSize), postQuery).getRecords();
        List<PostsDto> postsDtos = new ArrayList<>();
        for (Posts post : posts) {
            LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
            imageLambdaQueryWrapper = imageLambdaQueryWrapper.eq(Image::getPostsId, post.getId());
            List<Image> images = imageService.list(imageLambdaQueryWrapper);

            PostsDto postsDto = new PostsDto();
            postsDto.setUser(userService.getUser(post.getAccount()));
            postsDto.setAccount(post.getAccount());
            postsDto.setId(post.getId());
            postsDto.setText(post.getText());
            postsDto.setViewCount(post.getViewCount());
            postsDto.setUpdateDate(post.getUpdateDate());
            postsDto.setImages(images);
            if (account != null && !account.isBlank()) {
                LambdaQueryWrapper<Likes> likeQuery = new LambdaQueryWrapper<>();
                likeQuery.eq(Likes::getPostId, post.getId())
                        .eq(Likes::getAccount, account);
                postsDto.setIsLike(likeService.getOne(likeQuery) == null ? 0 : 1);
            } else {
                postsDto.setIsLike(0);
            }
            LambdaQueryWrapper<Likes> likeCountQuery = new LambdaQueryWrapper<>();
            likeCountQuery.eq(Likes::getPostId, post.getId());
            postsDto.setLikeCount(likeService.count(likeCountQuery));

            postsDtos.add(postsDto);
        }
        return R.success(postsDtos);
    }

    @GetMapping("/count")
    public R<String> count(@RequestParam String account) {
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper.in(Posts::getAccount, account);
        int count = (int) postsService.count(postsLambdaQueryWrapper);
        if (count > 0) {
            return R.success(String.valueOf(count));
        } else {
            return R.success("0");
        }
    }

    @DeleteMapping("/delete/{postId}")
    public R<String> deletePost(@PathVariable String postId, @RequestParam String account) {
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper.eq(Posts::getId, postId);

        //检查帖子是否存在
        Posts post = postsService.getOne(postsLambdaQueryWrapper);
        if (post == null) {
            return R.error("帖子不存在或已被删除");
        }
        if (!post.getAccount().equals(account)) {
            return R.error("无权删除其他用户的动态");
        }

        // 删除帖子
        boolean remove = postsService.remove(postsLambdaQueryWrapper);
        if (remove) {
            // 还需要删除关联的评论、图片等内容
            LambdaQueryWrapper<Comments> commentsLambdaQueryWrapper = new LambdaQueryWrapper<>();
            commentsLambdaQueryWrapper.eq(Comments::getPostsId, postId);
            commentsService.remove(commentsLambdaQueryWrapper);

            LambdaQueryWrapper<Likes> likesLambdaQueryWrapper = new LambdaQueryWrapper<>();
            likesLambdaQueryWrapper.eq(Likes::getPostId, postId);
            likeService.remove(likesLambdaQueryWrapper);

            LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
            imageLambdaQueryWrapper.eq(Image::getPostsId,postId);
            imageService.remove(imageLambdaQueryWrapper);
            return R.success("帖子删除成功");
        } else {
            return R.error("帖子删除失败");
        }
    }

}
