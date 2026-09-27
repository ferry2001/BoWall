package com.ferry.bowall.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ferry.bowall.common.R;
import com.ferry.bowall.entity.Image;
import com.ferry.bowall.service.ImageService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;


@RequestMapping("/image")
@RestController
@Slf4j
public class ImageController {
    private static final Set<String> IMAGE_EXTENSIONS = Set.of("jpg", "jpeg", "png", "gif");

    @Autowired
    private ImageService imageService;

    @Value("${app.upload-dir:${user.dir}/uploads}")
    private String uploadDir;

    @GetMapping("/getImage")
    public R<List<Image>> getImage(@RequestParam String account) {
        LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        LambdaQueryWrapper<Image> images = imageLambdaQueryWrapper.eq(Image::getAccount, account);
        List<Image> img = imageService.list(images);
        return R.success(img);
    }

    /**
     * post the image
     * @param images
     * @return
     * @throws IOException
     */
    @PostMapping("/post")
    public R<String> post(@RequestParam("images") MultipartFile images,
                          @RequestParam("account") String account,
                          @RequestParam("postId") String postId) throws IOException {
        if (images.isEmpty()) {
            return R.error("请选择图片");
        }
        String originalName = Optional.ofNullable(images.getOriginalFilename()).orElse("");
        int extensionStart = originalName.lastIndexOf('.') + 1;
        String extension = extensionStart > 0 ? originalName.substring(extensionStart).toLowerCase(Locale.ROOT) : "";
        if (!IMAGE_EXTENSIONS.contains(extension)) {
            return R.error("图片仅支持 JPG、PNG 或 GIF 格式");
        }

        Path directory = Path.of(uploadDir).toAbsolutePath();
        Files.createDirectories(directory);
        String fileName = UUID.randomUUID() + "." + extension;
        Path destination = directory.resolve(fileName);
        try (var input = images.getInputStream()) {
            Files.copy(input, destination, StandardCopyOption.REPLACE_EXISTING);
        }
        BufferedImage bufferedImage = ImageIO.read(destination.toFile());
        if (bufferedImage == null) {
            Files.deleteIfExists(destination);
            return R.error("无法读取图片内容");
        }

        Image image = new Image();
        image.setAccount(account);
        image.setUrl("/images/" + fileName);
        image.setPostsId(postId);
        image.setWidth(String.valueOf(bufferedImage.getWidth()));
        image.setHeight(String.valueOf(bufferedImage.getHeight()));
        image.setUpdateDate(LocalDateTime.now());
        if (!imageService.save(image)) {
            Files.deleteIfExists(destination);
            return R.error("图片记录保存失败");
        }
        log.info("图片已保存: postId={}, file={}", postId, fileName);

        return R.success("传输成功");
    }


}
