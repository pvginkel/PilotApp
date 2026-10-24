/** What the chat asks of the page around it: going to a quoted item or block. */

import { createContext, useContext } from 'react';
import type { QuoteRef } from '@/lib/chat/quotes';

export interface ChatActions {
  openQuote: (quote: QuoteRef) => void;
}

export const ChatActionsContext = createContext<ChatActions>({ openQuote: () => {} });

export const useChatActions = () => useContext(ChatActionsContext);
