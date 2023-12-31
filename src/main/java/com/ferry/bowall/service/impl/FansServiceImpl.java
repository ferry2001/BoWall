package com.ferry.bowall.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.ferry.bowall.entity.Fans;
import com.ferry.bowall.entity.User;
import com.ferry.bowall.mapper.FansMapper;
import com.ferry.bowall.mapper.UserMapper;
import com.ferry.bowall.service.FansService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import javax.persistence.EntityNotFoundException;
import java.util.List;

@Service
public class FansServiceImpl extends ServiceImpl<FansMapper, Fans> implements FansService {
    @Autowired
    private FansMapper fansMapper;

    @Autowired
    private UserMapper userMapper;

    @Override
    public Fans isfan(String account, String fansAccount) {
        Fans fans = fansMapper.isfan(account, fansAccount);
        if (fans != null) {
            System.out.println("exist");
        }
        return fans;
    }
}
