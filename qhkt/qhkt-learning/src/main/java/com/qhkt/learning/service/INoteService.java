package com.qhkt.learning.service;

import com.qhkt.common.domain.dto.PageDTO;
import com.qhkt.learning.domain.dto.NoteFormDTO;
import com.qhkt.learning.domain.po.Note;
import com.baomidou.mybatisplus.extension.service.IService;
import com.qhkt.learning.domain.query.NoteAdminPageQuery;
import com.qhkt.learning.domain.query.NotePageQuery;
import com.qhkt.learning.domain.vo.NoteAdminDetailVO;
import com.qhkt.learning.domain.vo.NoteAdminVO;
import com.qhkt.learning.domain.vo.NoteVO;

/**
 * <p>
 *  服务类
 * </p>
 *
 * @author 虎哥
 */
public interface INoteService extends IService<Note> {

    void saveNote(NoteFormDTO noteDTO);

    void gatherNote(Long id);

    void removeGatherNote(Long id);

    void updateNote(NoteFormDTO noteDTO);

    PageDTO<NoteVO> queryNotePage(NotePageQuery query);

    PageDTO<NoteAdminVO> queryNotePageForAdmin(NoteAdminPageQuery query);

    NoteAdminDetailVO queryNoteDetailForAdmin(Long id);

    void hiddenNote(Long id, boolean hidden);

    void removeMyNote(Long id);
}
