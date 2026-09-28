package com.ferry.bowall.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ferry.bowall.common.PinYin;
import com.ferry.bowall.common.R;
import com.ferry.bowall.common.JwtService;
import com.ferry.bowall.filter.JwtAuthInterceptor;
import com.ferry.bowall.entity.Fans;
import com.ferry.bowall.entity.User;
import com.ferry.bowall.service.FansService;
import com.ferry.bowall.service.MessageService;
import com.ferry.bowall.service.NotificationService;
import com.ferry.bowall.service.UserService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDateTime;
import java.util.*;
import javax.imageio.ImageIO;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;


@RequestMapping("/user")
@RestController
@Slf4j
public class UserController {
    private static final Set<String> IMAGE_EXTENSIONS = Set.of("jpg", "jpeg", "png", "gif", "webp");

    @Value("${app.upload-dir:${user.dir}/uploads}")
    private String uploadDir;
    @Autowired
    private NotificationService notificationService;

    @Autowired
    private UserService userService;

    @Autowired
    private MessageService messageService;

    @Autowired
    private FansService fansService;

    @Autowired
    private PinYin pinYin;

    @Autowired
    private JwtService jwtService;

    @GetMapping("/getUser")
    public R<User> getUser(String account) {
        User user = userService.getUser(account);
        if (user != null) {
            return R.success(user);
        } else {
            return R.error("用户不存在");
        }

    }

    /** 搜索页用户结果：账号与昵称均支持模糊匹配。 */
    @GetMapping("/search")
    public R<List<User>> search(@RequestParam String keyword) {
        String value = keyword == null ? "" : keyword.trim();
        if (value.isEmpty()) return R.success(Collections.emptyList());
        LambdaQueryWrapper<User> query = new LambdaQueryWrapper<>();
        query.like(User::getAccount, value)
                .or()
                .like(User::getName, value)
                .last("LIMIT 30");
        return R.success(userService.list(query));
    }

    @PostMapping("/add")
    public R<String> add(HttpServletRequest request, @RequestBody Map map) {
        String account = map.get("account").toString();
        String fansAccount = map.get("fansAccount").toString();
        String currentAccount = (String) request.getAttribute(JwtAuthInterceptor.CURRENT_ACCOUNT);
        if (!fansAccount.equals(currentAccount)) {
            return R.error("无权操作其他用户的关注关系");
        }
        if (account.equals(fansAccount)) {
            return R.error("不能关注自己");
        }
        if (userService.getUser(account) == null) {
            return R.error("用户不存在");
        }
        Fans isfan = fansService.isfan(account, fansAccount);
        if (isfan != null) {
            userService.deleteFanAndFollowUser(account, fansAccount);
            return R.success("取消关注");
        } else {
            userService.addFanAndFollowUser(account, fansAccount);
            return R.success("关注成功");
        }

    }

    @PostMapping("/login")
    public R<Map<String, Object>> login(@RequestBody Map map) {
        log.info(map.toString());

        //获取手机号
        String phone = map.get("phone").toString();

        //获取验证码
        String code = map.get("code").toString();

        //从 Session 中获取保存的验证码
        //Object codeInSession = session.getAttribute(phone);

       /* //从 Redis 中获取缓存的验证码
        Object codeInSession = redisTemplate.opsForValue().get(phone);*/

        String codeInSession = map.get("randomNum").toString();

        //进行验证码的比对（页面提交的验证码和Session中保存的验证码比对）
        if (codeInSession != null && codeInSession.equals(code)) {
            //如果能够比对成功，说明登录成功

            LambdaQueryWrapper<User> queryWrapper = new LambdaQueryWrapper<>();
            queryWrapper.eq(User::getPhone, phone);

            User user = userService.getOne(queryWrapper);
            if (user == null) {
                //判断当前手机号对应的用户是否为新用户，如果是新用户就自动完成注册
                user = new User();
                user.setAccount(UUID.randomUUID().toString());
                user.setPhone(phone);
                user.setStatus(1);
                userService.save(user);
            }
            Map<String, Object> loginResult = new HashMap<>();
            loginResult.put("token", jwtService.createToken(user.getAccount()));
            loginResult.put("user", user);
            return R.success(loginResult);
        }
        return R.error("登录失败");
    }


    @PutMapping
    public R<String> update(HttpServletRequest request, @RequestBody User user) {
        String currentAccount = (String) request.getAttribute(JwtAuthInterceptor.CURRENT_ACCOUNT);
        if (!currentAccount.equals(user.getAccount())) {
            return R.error("无权修改其他用户的资料");
        }
        user.setUpdateTime(LocalDateTime.now());
        userService.updateUser(user);
        return R.success("用户信息修改成功");
    }

    @PostMapping(value = "/avatar", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public R<User> uploadAvatar(
            HttpServletRequest request,
            @RequestParam String account,
            @RequestParam("avatar") MultipartFile avatar) throws IOException {
        String currentAccount = (String) request.getAttribute(JwtAuthInterceptor.CURRENT_ACCOUNT);
        if (!currentAccount.equals(account)) {
            return R.error("无权修改其他用户的头像");
        }
        if (avatar.isEmpty()) {
            return R.error("请选择头像图片");
        }
        User user = userService.getUser(account);
        if (user == null) {
            return R.error("用户不存在");
        }
        String originalName = Optional.ofNullable(avatar.getOriginalFilename()).orElse("");
        int extensionStart = originalName.lastIndexOf('.') + 1;
        String extension = extensionStart > 0
                ? originalName.substring(extensionStart).toLowerCase(Locale.ROOT) : "";
        if (!IMAGE_EXTENSIONS.contains(extension)) {
            return R.error("头像仅支持 JPG、PNG、GIF 或 WebP 格式");
        }
        Path directory = Path.of(uploadDir).toAbsolutePath();
        Files.createDirectories(directory);

        // === 核心：读图 -> 中心裁剪成正方形 -> 缩放到 400x400 ===
        BufferedImage original = ImageIO.read(avatar.getInputStream());
        if (original == null) {
            return R.error("无法读取图片内容");
        }
        int w = original.getWidth(), h = original.getHeight();
        int side = Math.min(w, h);
        BufferedImage squared = original.getSubimage((w - side) / 2, (h - side) / 2, side, side);
        boolean keepAlpha = "png".equals(extension);   // png 保留透明通道，避免黑底
        BufferedImage out = new BufferedImage(400, 400,
                keepAlpha ? BufferedImage.TYPE_INT_ARGB : BufferedImage.TYPE_INT_RGB);
        Graphics2D g2 = out.createGraphics();
        g2.setRenderingHint(RenderingHints.KEY_INTERPOLATION,
                RenderingHints.VALUE_INTERPOLATION_BICUBIC);
        g2.drawImage(squared, 0, 0, 400, 400, null);
        g2.dispose();

        // gif 只保留首帧，统一转 png；其余保持原格式
        String finalExt = extension.equals("gif") ? "png" : extension;
        String fileName = UUID.randomUUID() + "." + finalExt;
        ImageIO.write(out, finalExt, directory.resolve(fileName).toFile());

        user.setAvatar("/images/" + fileName);
        userService.updateUser(user);
        return R.success(user);
    }


    @GetMapping("/friends")
    public R<Map<String, List<User>>> friends(@RequestParam String account) {
        List<User> friends = userService.friends(account);

        Map<String, List<User>> groupedObjects = new HashMap<>();


        // Group objects
        for (User user : friends) {
            String objectName = user.getName();
            // Extract the first word and its pinyin
            String[] parts = objectName.split(" ");
            String firstName = parts[0];
            String py = pinYin.getPinyin(firstName);

            // Generate the grouping key
            String groupingKey = "";
            //if chinese
            if (!py.isEmpty()) {
                groupingKey = py.charAt(0) + "";
                //if english
            } else {
                groupingKey = firstName.charAt(0) + "";
            }
            //uppercase letter
            groupingKey = groupingKey.toUpperCase();
            // Add the object to the corresponding group
            if (groupedObjects.containsKey(groupingKey)) {
                groupedObjects.get(groupingKey).add(user);
            } else {
                List<User> objects = new ArrayList<>();
                objects.add(user);
                groupedObjects.put(groupingKey, objects);
            }
        }

        for (List<User> users : groupedObjects.values()) {
            Collections.sort(users, new Comparator<User>() {
                public int compare(User u1, User u2) {
                    return -(u1.getName().compareTo(u2.getName()));
                }
            });
        }

        //Sort map
        TreeMap<String, List<User>> treeMap = new TreeMap<>(groupedObjects);

        return R.success(treeMap);
    }

}
