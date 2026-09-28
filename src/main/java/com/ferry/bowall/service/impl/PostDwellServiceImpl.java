package com.ferry.bowall.service.impl;

import com.baomidou.mybatisplus.spring.service.impl.ServiceImpl;
import com.ferry.bowall.entity.PostDwell;
import com.ferry.bowall.mapper.PostDwellMapper;
import com.ferry.bowall.service.PostDwellService;
import org.springframework.stereotype.Service;

@Service
public class PostDwellServiceImpl extends ServiceImpl<PostDwellMapper, PostDwell> implements PostDwellService {
}
