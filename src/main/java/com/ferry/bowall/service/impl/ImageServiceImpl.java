package com.ferry.bowall.service.impl;

import com.baomidou.mybatisplus.spring.service.impl.ServiceImpl;
import com.ferry.bowall.mapper.ImageMapper;
import com.ferry.bowall.entity.Image;
import com.ferry.bowall.service.ImageService;
import org.springframework.stereotype.Service;

@Service
public class ImageServiceImpl extends ServiceImpl<ImageMapper, Image> implements ImageService {
}
