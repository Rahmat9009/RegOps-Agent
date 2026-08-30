// PageTransition.tsx — The route entrance.
//
// One restrained move: the incoming view fades up over 320 ms. There is no exit
// animation, because a demo cannot afford to wait for one, and nothing staggers
// at this level — a whole screen sliding in piece by piece reads as decoration.
//
// Under prefers-reduced-motion the wrapper renders the view with no animation at
// all rather than a fast one, so no transform is ever applied.

import { motion, useReducedMotion } from "framer-motion";
import { useLocation } from "react-router-dom";

export function PageTransition({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  const reduceMotion = useReducedMotion();

  if (reduceMotion) {
    return <div className="page__view">{children}</div>;
  }

  return (
    <motion.div
      key={pathname}
      className="page__view"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: [0.2, 0, 0, 1] }}
    >
      {children}
    </motion.div>
  );
}
