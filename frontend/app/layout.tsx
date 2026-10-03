import './globals.css'; import type { Metadata } from 'next';
export const metadata:Metadata={title:'MERADION — Student voices, privately connected',description:'Private educational audio for schools and families.'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
