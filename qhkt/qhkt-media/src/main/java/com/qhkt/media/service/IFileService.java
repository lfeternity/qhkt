package com.qhkt.media.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.qhkt.media.domain.dto.FileDTO;
import com.qhkt.media.domain.po.File;
import org.springframework.web.multipart.MultipartFile;

/**
 * <p>
 * 文件表，可以是普通文件、图片等 服务类
 * </p>
 *
 * @author 虎哥
 * @since 2022-06-30
 */
public interface IFileService extends IService<File> {

    FileDTO uploadFile(MultipartFile file);

    FileDTO getFileInfo(Long id);
}
