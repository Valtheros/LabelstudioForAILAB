import React from "react";
import { unique } from "../../../utils/helpers";

export const useImportPage = () => {
  const [uploading, setUploadingStatus] = React.useState(false);
  const [columns, setColumns] = React.useState([]);

  const pageProps = {
    onWaiting: setUploadingStatus,
    addColumns: (cols) => setColumns((current) => unique(current.concat(cols))),
  };

  return { columns, uploading, pageProps };
};
