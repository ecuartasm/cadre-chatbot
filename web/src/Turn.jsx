import { renderInline } from './markdown.jsx'

/**
 * One turn in a transcript, shared by the full-page chat and the floating widget.
 *
 * ⚠️ **Extracted because duplicating it defeated its own guard.** The markup lived twice, and
 * `test_only_assistant_text_is_formatted` searches *all* sources for the formatting rule — so if
 * one copy had regressed, the other would have satisfied the assertion and the suite would have
 * stayed green. Two copies of a rule mean the test can only prove that *somewhere* obeys it.
 *
 * The rule it protects: **only assistant prose is formatted.** The user typed their own asterisks
 * and reinterpreting them would be surprising, and an error frame is server text, not model
 * output — running either through the markdown renderer would be wrong.
 *
 * The two surfaces differ only in class names, so those are parameters. Everything that could be
 * wrong — which speaker, what gets formatted, where the caret goes — is decided once, here.
 */
export default function Turn({ message, isLast, streaming, classes }) {
  const isUser = message.role === 'user'
  return (
    <p className={isUser ? `${classes.turn} ${classes.turnUser}` : classes.turn}>
      <span className={classes.speaker}>{isUser ? 'You' : 'Cadre AI'}</span>
      <span className={message.isError ? 'message message--error' : 'message'}>
        {message.role === 'assistant' && !message.isError
          ? renderInline(message.content)
          : message.content}
        {streaming && isLast && message.role === 'assistant' && <span className="caret">▍</span>}
      </span>
    </p>
  )
}
