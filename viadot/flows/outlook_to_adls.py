import os
from typing import Any, Dict, List, Union, Literal

import pendulum
from prefect import Flow, Task, apply_map, task
import pandas as pd
from ..utils import slugify
from ..task_utils import df_to_csv, union_dfs_task

from ..tasks import OutlookToDF, AzureDataLakeUpload

file_to_adls_task = AzureDataLakeUpload()
outlook_to_df = OutlookToDF()


class OutlookToCSVs(Flow):
    def __init__(
        self,
        mailbox_list: List[str],
        name: str = None,
        start_date: str = None,
        end_date: str = None,
        local_file_path: str = None,
        extension_file: str = ".csv",
        adls_file_path: str = None,
        overwrite_adls: bool = True,
        adls_sp_credentials_secret: str = None,
        limit: int = 10000,
        if_exists: Literal["append", "replace", "skip"] = "append",
        *args: List[Any],
        **kwargs: Dict[str, Any],
    ):
        """Flow for downloading data from Outlook source to a local CSV
        using Outlook API, then uploading it to Azure Data Lake.

        Args:
            mailbox_list (List[str]): Mailbox name.
            name (str, optional): The name of the flow. Defaults to None.
            start_date (str, optional): A filtering start date parameter e.g. "2022-01-01". Defaults to None.
            end_date (str, optional): A filtering end date parameter e.g. "2022-01-02". Defaults to None.
            local_file_path (str, optional): Local destination path. Defaults to None.
            extension_file (str, optional): Output file extension. Defaults to ".csv".
            adls_file_path (str, optional): Azure Data Lake destination file path. Defaults to None.
            overwrite_adls (bool, optional): Whether to overwrite the file in ADLS. Defaults to True.
            adls_sp_credentials_secret (str, optional): The name of the Azure Key Vault secret containing a dictionary with
            ACCOUNT_NAME and Service Principal credentials (TENANT_ID, CLIENT_ID, CLIENT_SECRET) for the Azure Data Lake. Defaults to None.
            limit (int, optional): Number of fetched top messages. Defaults to 10000.
            if_exists (Literal['append', 'replace', 'skip'], optional): What to do if the local file already exists. Defaults to "append".
        """

        self.mailbox_list = mailbox_list
        self.start_date = start_date
        self.end_date = end_date
        self.limit = limit
        self.local_file_path = local_file_path
        self.if_exsists = if_exists

        # AzureDataLakeUpload
        self.adls_file_path = adls_file_path
        self.extension_file = extension_file
        self.overwrite_adls = overwrite_adls
        self.adls_sp_credentials_secret = adls_sp_credentials_secret

        super().__init__(*args, name=name, **kwargs)

        self.gen_flow()

    def gen_outlook_df(
        self, mailbox_list: Union[str, List[str]], flow: Flow = None
    ) -> Task:

        report = outlook_to_df.bind(
            mailbox_name=mailbox_list,
            start_date=self.start_date,
            end_date=self.end_date,
            limit=self.limit,
            flow=flow,
        )

        return report

    def gen_flow(self) -> Flow:

        dfs = apply_map(self.gen_outlook_df, self.mailbox_list, flow=self)

        df = union_dfs_task.bind(dfs, flow=self)

        df_to_file = df_to_csv.bind(
            df=df, path=self.local_file_path, if_exists=self.if_exsists, flow=self
        )

        file_to_adls_task.bind(
            from_path=self.local_file_path,
            to_path=self.adls_file_path,
            overwrite=self.overwrite_adls,
            sp_credentials_secret=self.adls_sp_credentials_secret,
            flow=self,
        )

        df_to_file.set_upstream(df, flow=self)
        file_to_adls_task.set_upstream(df_to_file, flow=self)
