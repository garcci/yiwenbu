# TTS2字幕支持核查：不改变本批请求

2026-11-02本次只读资料核查发现，火山普通单向HTTP文档列有`req_params.audio_params.enable_subtitle`，说明开启后返回字级时间戳；SSE资料说明TTS2返回TTSSubtitle事件，而enable_timestamp仅适用于TTS1。官方资料入口：

- https://docs.volcengine.com/docs/doubao-voice/unidirectional-streaming-text-to-speech-http?lang=zh
- https://docs.volcengine.com/docs/doubao-voice/http-chunked-sse-unidirectional-streaming-v3?lang=zh

这不能证明方舟套餐`/api/v3/plan/tts/unidirectional`同样接受该字段。本次未找到直接的套餐路径证明；套餐专页抓取超时，BytePlus给定页面抓取只返回JS页面外壳。因此不把普通语音接口/SSE的说明直接推广为本套餐接口支持，不改变本批生成参数。

当前事件解析只拼接data音频并检查完成码，不保存sentence或TTSSubtitle；即使服务器返回这些字段也会忽略。没有声称本批会得到原生字幕或完成字幕对齐，也未用音频重新生成来试探参数。

下一步按主代理决定，在音频原件返回后使用已核查套餐范围内的云端ASR做校准。需要先确认ASR具体套餐端点、当前额度及其返回时间单位，不盲切普通按量ASR；在证据不足前保留原音，字幕不得按字数估计后冒称实际同步。ASR文字与人名也须对照冻结正文检查；云端ASR结果不证明听感、语气或逐字时间完全准确。本机不运行模型。
