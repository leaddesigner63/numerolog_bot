# CONTRIBUTING

## Обязательный паттерн для текстового ввода после callback

Для **любого** сценария, где после нажатия inline-кнопки бот переходит в ожидание текстового ответа пользователя,
нужно использовать единый helper:

- `screen_manager.enter_text_input_mode(...)`

### Почему это обязательно

- снимаются устаревшие inline-клавиатуры с активного экрана;
- удаляется предыдущее вопросное сообщение (или сохраняется при `preserve_last_question=True`);
- снижается риск конфликтов между старым экраном и новым шагом ввода.

### Как применять

1. Если callback **сразу** запускает текстовый ввод:
   - вызовите `enter_text_input_mode(bot=..., chat_id=..., user_id=...)`;
2. Если `delete_last_question_message(...)` уже был вызван ранее в этом же шаге:
   - используйте `enter_text_input_mode(..., preserve_last_question=True)`.

### Минимальный пример

```python
await screen_manager.enter_text_input_mode(
    bot=callback.bot,
    chat_id=callback.message.chat.id,
    user_id=callback.from_user.id,
)
```

### Требование к тестам

Для каждого нового callback-сценария с ожиданием текста добавляйте тест, который проверяет вызов
`enter_text_input_mode(...)`.
