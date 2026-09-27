package com.ferry.bowall.config;

import com.ferry.bowall.common.JacksonObjectMapper;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.util.List;
import java.nio.file.Path;

@Slf4j
@Configuration
public class WebMvcConfig implements WebMvcConfigurer {

    @Value("${app.upload-dir:${user.dir}/uploads}")
    private String uploadDir;


    /**
     * 设置静态资源映射
     * @param registry
     */
    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        log.info("开始进行静态资源映射...");
        registry.addResourceHandler("/images/**")
                .addResourceLocations(Path.of(uploadDir).toAbsolutePath().toUri().toString());
    }

    /**
     * 扩展 MVC 框架的消息转换器
     * @param converters
     */
    @Override
    @SuppressWarnings("removal") // Spring Framework 7 still supports this Jackson 2 compatibility bridge.
    public void extendMessageConverters(List<HttpMessageConverter<?>> converters) {

        log.info("扩展消息转换器...");

        //创建消息转换器对象
        MappingJackson2HttpMessageConverter messageConverter = new MappingJackson2HttpMessageConverter();

        //设置对象转换器，底层使用 Jackson 将 Java 对象转化为 json
        messageConverter.setObjectMapper(new JacksonObjectMapper());


        //将上面的消息转换器对象追加到 mvc 框架的转换集合中
        converters.add(0, messageConverter);

    }

    @Bean
    public OpenAPI bowallOpenApi() {
        return new OpenAPI().info(new Info()
                .title("BoWall")
                .version("1.0.0")
                .description("BoWall interface doc"));
    }
}
